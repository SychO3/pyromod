from inspect import iscoroutinefunction
from typing import Callable

import pyrogram
from pyrogram.filters import Filter
from pyrogram.types import Message

from .client import Client
from ..types import ListenerTypes, Identifier
from ..utils import should_patch, patch_into

LISTENER_CACHE_ATTR = "_pyromod_listener_resolution_cache"


@patch_into(pyrogram.handlers.message_handler.MessageHandler)
class MessageHandler(pyrogram.handlers.message_handler.MessageHandler):
    filters: Filter
    old__init__: Callable

    @should_patch()
    def __init__(self, callback: Callable, filters: Filter = None):
        self.original_callback = callback
        self.old__init__(self.resolve_future_or_callback, filters)

    @should_patch()
    def _cache_listener_resolution(self, message: Message, resolution):
        cache = getattr(message, LISTENER_CACHE_ATTR, None)
        if cache is None:
            cache = {}
            setattr(message, LISTENER_CACHE_ATTR, cache)

        cache[id(self)] = resolution

    @should_patch()
    def _pop_cached_listener_resolution(self, message: Message):
        cache = getattr(message, LISTENER_CACHE_ATTR, None)
        if cache is None:
            return None

        resolution = cache.pop(id(self), None)

        if not cache:
            delattr(message, LISTENER_CACHE_ATTR)

        return resolution

    @should_patch()
    async def check_if_has_matching_listener(self, client: Client, message: Message):
        from_user = message.from_user
        from_user_id = from_user.id if from_user else None
        from_user_username = from_user.username if from_user else None

        message_id = getattr(message, "id", getattr(message, "message_id", None))

        data = Identifier(
            message_id=message_id,
            chat_id=[message.chat.id, message.chat.username],
            from_user_id=[from_user_id, from_user_username],
        )

        listener = client.get_listener_matching_with_data(data, ListenerTypes.MESSAGE)

        listener_does_match = False

        if listener:
            filters = listener.filters
            if callable(filters):
                if iscoroutinefunction(filters.__call__):
                    listener_does_match = await filters(client, message)
                else:
                    listener_does_match = await client.loop.run_in_executor(
                        None, filters, client, message
                    )
            else:
                listener_does_match = True

        return listener_does_match, listener

    @should_patch()
    async def check(self, client: Client, message: Message):
        resolution = await self.check_if_has_matching_listener(client, message)
        listener_does_match = resolution[0]

        if callable(self.filters):
            if iscoroutinefunction(self.filters.__call__):
                handler_does_match = await self.filters(client, message)
            else:
                handler_does_match = await client.loop.run_in_executor(
                    None, self.filters, client, message
                )
        else:
            handler_does_match = True

        # let handler get the chance to handle if listener
        # exists but its filters doesn't match
        should_handle_update = listener_does_match or handler_does_match

        if should_handle_update:
            self._cache_listener_resolution(message, resolution)

        return should_handle_update

    @should_patch()
    async def resolve_future_or_callback(self, client: Client, message: Message, *args):
        resolution = self._pop_cached_listener_resolution(message)

        if resolution is None:
            resolution = await self.check_if_has_matching_listener(client, message)

        listener_does_match, listener = resolution

        if (
            listener
            and listener_does_match
            and listener not in client.listeners[listener.listener_type]
        ):
            listener_does_match, listener = await self.check_if_has_matching_listener(
                client, message
            )

        if listener and listener_does_match:
            client.remove_listener(listener)

            if listener.future and not listener.future.done():
                listener.future.set_result(message)

                raise pyrogram.StopPropagation
            elif listener.callback:
                if iscoroutinefunction(listener.callback):
                    await listener.callback(client, message, *args)
                else:
                    listener.callback(client, message, *args)

                raise pyrogram.StopPropagation
            else:
                raise ValueError("Listener must have either a future or a callback")
        else:
            await self.original_callback(client, message, *args)
