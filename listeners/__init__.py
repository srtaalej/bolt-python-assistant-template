from listeners.assistant import assistant
from listeners.assistant.assistant import handle_feedback


def register_listeners(app):
    # Using assistant middleware is the recommended way.
    app.assistant(assistant)
    app.action("feedback")(handle_feedback)

    # The following event listeners demonstrate how to implement the same on your own.
    # from listeners import events
    # events.register(app)
