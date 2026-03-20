import asyncio
from functools import partial
from inspect import Parameter, iscoroutinefunction, signature
from typing import Optional, Callable, Dict, List, Union

import pyrogram
from pyrogram.filters import Filter

from ..config import config
from ..exceptions import ListenerTimeout, ListenerStopped
from ..types import ListenerTypes, Identifier, Listener
from ..utils import should_patch, patch_into

if not config.disable_startup_logs:
    print(
        "Pyromod is working! If you like pyromod, please star it at https://github.com/usernein/pyromod"
    )

INDEXED_IDENTIFIER_FIELDS = (
    "inline_message_id",
    "message_id",
    "chat_id",
    "from_user_id",
)


@patch_into(pyrogram.client.Client)
class Client(pyrogram.Client):
    listeners: Dict[ListenerTypes, List[Listener]]
    old__init__: Callable

    @should_patch()
    def __init__(self, *args, **kwargs):
        self.listeners = {listener_type: [] for listener_type in ListenerTypes}
        self.listener_indexes = {
            listener_type: {
                field_name: {"values": {}, "wildcards": {}}
                for field_name in INDEXED_IDENTIFIER_FIELDS
            }
            for listener_type in ListenerTypes
        }
        self.old__init__(*args, **kwargs)

    @should_patch()
    def _normalize_identifier_values(self, value):
        if value is None:
            return ()

        if isinstance(value, list):
            return tuple(dict.fromkeys(item for item in value if item is not None))

        return (value,)

    @should_patch()
    def _index_listener(self, listener: Listener):
        listener_id = id(listener)
        field_indexes = self.listener_indexes[listener.listener_type]

        for field_name in INDEXED_IDENTIFIER_FIELDS:
            field_index = field_indexes[field_name]
            values = self._normalize_identifier_values(
                getattr(listener.identifier, field_name)
            )

            if not values:
                field_index["wildcards"][listener_id] = listener
                continue

            for value in values:
                field_index["values"].setdefault(value, {})[listener_id] = listener

    @should_patch()
    def _deindex_listener(self, listener: Listener):
        listener_id = id(listener)
        field_indexes = self.listener_indexes[listener.listener_type]

        for field_name in INDEXED_IDENTIFIER_FIELDS:
            field_index = field_indexes[field_name]
            values = self._normalize_identifier_values(
                getattr(listener.identifier, field_name)
            )

            if not values:
                field_index["wildcards"].pop(listener_id, None)
                continue

            for value in values:
                listeners_for_value = field_index["values"].get(value)
                if listeners_for_value is None:
                    continue

                listeners_for_value.pop(listener_id, None)
                if not listeners_for_value:
                    field_index["values"].pop(value, None)

    @should_patch()
    def _get_indexed_candidates_for_data(
        self, data: Identifier, listener_type: ListenerTypes
    ) -> List[Listener]:
        best_candidates = None
        field_indexes = self.listener_indexes[listener_type]

        for field_name in INDEXED_IDENTIFIER_FIELDS:
            values = self._normalize_identifier_values(getattr(data, field_name))
            if not values:
                continue

            field_index = field_indexes[field_name]
            candidate_map = dict(field_index["wildcards"])

            for value in values:
                candidate_map.update(field_index["values"].get(value, {}))

            if best_candidates is None or len(candidate_map) < len(best_candidates):
                best_candidates = candidate_map

            if best_candidates is not None and len(best_candidates) <= 1:
                break

        if best_candidates is None:
            return list(self.listeners[listener_type])

        return list(best_candidates.values())

    @should_patch()
    def _get_indexed_candidates_for_pattern(
        self, pattern: Identifier, listener_type: ListenerTypes
    ) -> List[Listener]:
        best_candidates = None
        field_indexes = self.listener_indexes[listener_type]

        for field_name in INDEXED_IDENTIFIER_FIELDS:
            values = self._normalize_identifier_values(getattr(pattern, field_name))
            if not values:
                continue

            field_index = field_indexes[field_name]
            candidate_map = {}

            for value in values:
                candidate_map.update(field_index["values"].get(value, {}))

            if best_candidates is None or len(candidate_map) < len(best_candidates):
                best_candidates = candidate_map

            if best_candidates is not None and len(best_candidates) <= 1:
                break

        if best_candidates is None:
            return list(self.listeners[listener_type])

        return list(best_candidates.values())

    @should_patch()
    def _add_listener(self, listener: Listener):
        self.listeners[listener.listener_type].append(listener)
        self._index_listener(listener)

    @should_patch()
    def _is_coroutine_callable(self, callback: Callable) -> bool:
        return iscoroutinefunction(callback) or iscoroutinefunction(
            getattr(callback, "__call__", None)
        )

    @should_patch()
    def _get_timeout_handler_call_args(self, listener: Listener, timeout: Optional[int]):
        handler = config.timeout_handler
        args = (listener.identifier, listener, timeout)
        kwargs = {}

        try:
            parameters = signature(handler).parameters.values()
        except (TypeError, ValueError):
            return args, kwargs

        positional_params = 0
        accepts_var_positional = False
        accepts_var_keyword = False
        has_sent_message_parameter = False

        for parameter in parameters:
            if parameter.kind == Parameter.VAR_POSITIONAL:
                accepts_var_positional = True
                continue

            if parameter.kind == Parameter.VAR_KEYWORD:
                accepts_var_keyword = True
                continue

            if parameter.kind in (
                Parameter.POSITIONAL_ONLY,
                Parameter.POSITIONAL_OR_KEYWORD,
            ):
                positional_params += 1

            if parameter.name == "sent_message":
                has_sent_message_parameter = True

        if accepts_var_positional or positional_params >= 4:
            return args + (listener.sent_message,), kwargs

        if has_sent_message_parameter or accepts_var_keyword:
            kwargs["sent_message"] = listener.sent_message

        return args, kwargs

    @should_patch()
    async def _invoke_callable(self, callback: Callable, *args, **kwargs):
        if self._is_coroutine_callable(callback):
            return await callback(*args, **kwargs)

        return await self.loop.run_in_executor(
            None,
            partial(callback, *args, **kwargs),
        )

    @should_patch()
    async def listen(
        self,
        filters: Optional[Filter] = None,
        listener_type: ListenerTypes = ListenerTypes.MESSAGE,
        timeout: Optional[int] = None,
        unallowed_click_alert: bool = True,
        chat_id: Union[Union[int, str], List[Union[int, str]]] = None,
        user_id: Union[Union[int, str], List[Union[int, str]]] = None,
        message_id: Union[int, List[int]] = None,
        inline_message_id: Union[str, List[str]] = None,
        sent_message=None,
    ):
        pattern = Identifier(
            from_user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
        )

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        listener = Listener(
            future=future,
            filters=filters,
            unallowed_click_alert=unallowed_click_alert,
            identifier=pattern,
            listener_type=listener_type,
            sent_message=sent_message,
        )

        future.add_done_callback(lambda _future: self.remove_listener(listener))

        self._add_listener(listener)

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.exceptions.TimeoutError:
            if callable(config.timeout_handler):
                handler_args, handler_kwargs = self._get_timeout_handler_call_args(
                    listener, timeout
                )
                await self._invoke_callable(
                    config.timeout_handler, *handler_args, **handler_kwargs
                )
            elif config.throw_exceptions:
                raise ListenerTimeout(timeout)

    @should_patch()
    async def ask(
        self,
        chat_id: Union[Union[int, str], List[Union[int, str]]],
        text: str,
        filters: Optional[Filter] = None,
        listener_type: ListenerTypes = ListenerTypes.MESSAGE,
        timeout: Optional[int] = None,
        unallowed_click_alert: bool = True,
        user_id: Union[Union[int, str], List[Union[int, str]]] = None,
        message_id: Union[int, List[int]] = None,
        inline_message_id: Union[str, List[str]] = None,
        *args,
        **kwargs,
    ):
        sent_message = None
        if text.strip() != "":
            chat_to_ask = chat_id[0] if isinstance(chat_id, list) else chat_id
            sent_message = await self.send_message(chat_to_ask, text, *args, **kwargs)

        response = await self.listen(
            filters=filters,
            listener_type=listener_type,
            timeout=timeout,
            unallowed_click_alert=unallowed_click_alert,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            sent_message=sent_message,
        )
        if response:
            response.sent_message = sent_message

        return response

    @should_patch()
    def remove_listener(self, listener: Listener):
        try:
            self.listeners[listener.listener_type].remove(listener)
            self._deindex_listener(listener)
        except ValueError:
            pass

    @should_patch()
    def get_listener_matching_with_data(
        self, data: Identifier, listener_type: ListenerTypes
    ) -> Optional[Listener]:
        matching = []
        for listener in self._get_indexed_candidates_for_data(data, listener_type):
            if listener.identifier.matches(data):
                matching.append(listener)

        # in case of multiple matching listeners, the most specific should be returned
        def count_populated_attributes(listener_item: Listener):
            return listener_item.identifier.count_populated()

        return max(matching, key=count_populated_attributes, default=None)

    @should_patch()
    def get_listener_matching_with_identifier_pattern(
        self, pattern: Identifier, listener_type: ListenerTypes
    ) -> Optional[Listener]:
        matching = []
        for listener in self._get_indexed_candidates_for_pattern(
            pattern, listener_type
        ):
            if pattern.matches(listener.identifier):
                matching.append(listener)

        # in case of multiple matching listeners, the most specific should be returned

        def count_populated_attributes(listener_item: Listener):
            return listener_item.identifier.count_populated()

        return max(matching, key=count_populated_attributes, default=None)

    @should_patch()
    def get_many_listeners_matching_with_data(
        self,
        data: Identifier,
        listener_type: ListenerTypes,
    ) -> List[Listener]:
        listeners = []
        for listener in self._get_indexed_candidates_for_data(data, listener_type):
            if listener.identifier.matches(data):
                listeners.append(listener)
        return listeners

    @should_patch()
    def get_many_listeners_matching_with_identifier_pattern(
        self,
        pattern: Identifier,
        listener_type: ListenerTypes,
    ) -> List[Listener]:
        listeners = []
        for listener in self._get_indexed_candidates_for_pattern(
            pattern, listener_type
        ):
            if pattern.matches(listener.identifier):
                listeners.append(listener)
        return listeners

    @should_patch()
    async def stop_listening(
        self,
        listener_type: ListenerTypes = ListenerTypes.MESSAGE,
        chat_id: Union[Union[int, str], List[Union[int, str]]] = None,
        user_id: Union[Union[int, str], List[Union[int, str]]] = None,
        message_id: Union[int, List[int]] = None,
        inline_message_id: Union[str, List[str]] = None,
    ):
        pattern = Identifier(
            from_user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
        )
        listeners = self.get_many_listeners_matching_with_identifier_pattern(pattern, listener_type)

        for listener in listeners:
            await self.stop_listener(listener)

    @should_patch()
    async def stop_listener(self, listener: Listener):
        self.remove_listener(listener)

        if listener.future.done():
            return

        if callable(config.stopped_handler):
            await self._invoke_callable(config.stopped_handler, None, listener)
        elif config.throw_exceptions:
            listener.future.set_exception(ListenerStopped())

    @should_patch()
    def register_next_step_handler(
        self,
        callback: Callable,
        filters: Optional[Filter] = None,
        listener_type: ListenerTypes = ListenerTypes.MESSAGE,
        unallowed_click_alert: bool = True,
        chat_id: Union[Union[int, str], List[Union[int, str]]] = None,
        user_id: Union[Union[int, str], List[Union[int, str]]] = None,
        message_id: Union[int, List[int]] = None,
        inline_message_id: Union[str, List[str]] = None,
    ):
        pattern = Identifier(
            from_user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
        )

        listener = Listener(
            callback=callback,
            filters=filters,
            unallowed_click_alert=unallowed_click_alert,
            identifier=pattern,
            listener_type=listener_type,
        )

        self._add_listener(listener)
