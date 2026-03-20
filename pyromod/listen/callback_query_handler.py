from inspect import iscoroutinefunction
from typing import Callable, Tuple

import pyrogram
from pyrogram.filters import Filter
from pyrogram.types import CallbackQuery

from .client import Client
from ..config import config
from ..types import ListenerTypes, Identifier, Listener
from ..utils import patch_into, should_patch


@patch_into(pyrogram.handlers.callback_query_handler.CallbackQueryHandler)
class CallbackQueryHandler(
    pyrogram.handlers.callback_query_handler.CallbackQueryHandler
):
    _listener_cache_attr = "_pyromod_listener_resolution_cache"
    old__init__: Callable

    @should_patch()
    def __init__(self, callback: Callable, filters: Filter = None):
        self.original_callback = callback
        self.old__init__(self.resolve_future_or_callback, filters)

    @should_patch()
    def _cache_listener_resolution(self, query: CallbackQuery, resolution):
        cache = getattr(query, self._listener_cache_attr, None)
        if cache is None:
            cache = {}
            setattr(query, self._listener_cache_attr, cache)

        cache[id(self)] = resolution

    @should_patch()
    def _pop_cached_listener_resolution(self, query: CallbackQuery):
        cache = getattr(query, self._listener_cache_attr, None)
        if cache is None:
            return None

        resolution = cache.pop(id(self), None)

        if not cache:
            delattr(query, self._listener_cache_attr)

        return resolution

    @should_patch()
    def compose_data_identifier(self, query: CallbackQuery):
        from_user = query.from_user
        from_user_id = from_user.id if from_user else None
        from_user_username = from_user.username if from_user else None

        chat_id = None
        message_id = None

        if query.message:
            message_id = getattr(
                query.message, "id", getattr(query.message, "message_id", None)
            )

            if query.message.chat:
                chat_id = [query.message.chat.id, query.message.chat.username]

        return Identifier(
            message_id=message_id,
            chat_id=chat_id,
            from_user_id=[from_user_id, from_user_username],
            inline_message_id=query.inline_message_id,
        )

    @should_patch()
    async def check_if_has_matching_listener(
        self, client: Client, query: CallbackQuery, data: Identifier = None
    ) -> Tuple[bool, Listener]:
        data = data or self.compose_data_identifier(query)

        listener = client.get_listener_matching_with_data(
            data, ListenerTypes.CALLBACK_QUERY
        )

        listener_does_match = False

        if listener:
            filters = listener.filters
            if callable(filters):
                if iscoroutinefunction(filters.__call__):
                    listener_does_match = await filters(client, query)
                else:
                    listener_does_match = await client.loop.run_in_executor(
                        None, filters, client, query
                    )
            else:
                listener_does_match = True

        return listener_does_match, listener

    @should_patch()
    async def check(self, client: Client, query: CallbackQuery):
        data = self.compose_data_identifier(query)
        resolution = await self.check_if_has_matching_listener(client, query, data)
        listener_does_match, listener = resolution

        if callable(self.filters):
            if iscoroutinefunction(self.filters.__call__):
                handler_does_match = await self.filters(client, query)
            else:
                handler_does_match = await client.loop.run_in_executor(
                    None, self.filters, client, query
                )
        else:
            handler_does_match = True

        if config.unallowed_click_alert and not listener_does_match:
            # Match any listener attached to this callback target, regardless of user.
            permissive_identifier = Identifier(
                chat_id=data.chat_id,
                message_id=data.message_id,
                inline_message_id=data.inline_message_id,
                from_user_id=None,
            )
            permissive_listener = client.get_listener_matching_with_identifier_pattern(
                permissive_identifier, ListenerTypes.CALLBACK_QUERY
            )

            if (
                permissive_listener
                and permissive_listener.unallowed_click_alert
            ):
                alert = (
                    permissive_listener.unallowed_click_alert
                    if isinstance(permissive_listener.unallowed_click_alert, str)
                    else config.unallowed_click_alert_text
                )
                await query.answer(alert)
                return False

        # let handler get the chance to handle if listener
        # exists but its filters doesn't match
        should_handle_update = listener_does_match or handler_does_match

        if should_handle_update:
            self._cache_listener_resolution(query, resolution)

        return should_handle_update

    @should_patch()
    async def resolve_future_or_callback(
        self, client: Client, query: CallbackQuery, *args
    ):
        resolution = self._pop_cached_listener_resolution(query)

        if resolution is None:
            resolution = await self.check_if_has_matching_listener(client, query)

        listener_does_match, listener = resolution

        if (
            listener
            and listener_does_match
            and listener not in client.listeners[listener.listener_type]
        ):
            listener_does_match, listener = await self.check_if_has_matching_listener(
                client, query
            )

        if listener and listener_does_match:
            client.remove_listener(listener)

            if listener.future and not listener.future.done():
                listener.future.set_result(query)

                raise pyrogram.StopPropagation
            elif listener.callback:
                if iscoroutinefunction(listener.callback):
                    await listener.callback(client, query, *args)
                else:
                    listener.callback(client, query, *args)

                raise pyrogram.StopPropagation
            else:
                raise ValueError("Listener must have either a future or a callback")
        else:
            await self.original_callback(client, query, *args)
