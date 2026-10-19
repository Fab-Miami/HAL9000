import asyncio

_active_tool_callbacks = set()

def register_tool_callback(callback):
    """Registers an async or sync callback to receive tool execution events."""
    _active_tool_callbacks.add(callback)

def unregister_tool_callback(callback):
    """Unregisters a previously registered tool callback."""
    _active_tool_callbacks.discard(callback)

def notify_tool_execution(tool_name: str):
    """Dispatches a notification to all registered active WebSocket sessions."""
    for cb in list(_active_tool_callbacks):
        try:
            if asyncio.iscoroutinefunction(cb):
                # Schedule in the running event loop if one is active
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(cb(tool_name))
                except RuntimeError:
                    pass
            else:
                cb(tool_name)
        except Exception as e:
            print(f"⚠️ [ToolEvents] Notification error: {e}")
