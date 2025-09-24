import logging
from typing import List, Dict
from slack_bolt import Assistant, BoltContext, Say, SetSuggestedPrompts
from slack_bolt.context.get_thread_context import GetThreadContext
from slack_sdk import WebClient
from slack_sdk.models.blocks import FeedbackButtonsElement, FeedbackButtonObject, ContextActionsBlock

from ..llm_caller import call_llm

# Refer to https://tools.slack.dev/bolt-python/concepts/assistant/ for more details
assistant = Assistant()


def create_feedback_block(user_id: str) -> ContextActionsBlock:
    """
    Create feedback block with thumbs up/down buttons

    Args:
        user_id: User ID for user-specific controls

    Returns:
        Block Kit context_actions block
    """
    block = [
        ContextActionsBlock(
            elements=[
                FeedbackButtonsElement(
                    action_id="feedback",
                    positive_button=FeedbackButtonObject(
                        text="Good Response",
                        accessibility_label="Submit positive feedback on this response",
                        value="good-feedback",
                    ),
                    negative_button=FeedbackButtonObject(
                        text="Bad Response",
                        accessibility_label="Submit negative feedback on this response",
                        value="bad-feedback",
                    ),
                )
            ]
        )
    ]
    return block


# This listener is invoked when a human user opened an assistant thread
@assistant.thread_started
def start_assistant_thread(
    say: Say,
    get_thread_context: GetThreadContext,
    set_suggested_prompts: SetSuggestedPrompts,
    logger: logging.Logger,
):
    try:
        say("How can I help you?")

        prompts: List[Dict[str, str]] = [
            {
                "title": "What does Slack stand for?",
                "message": "Slack, a business communication service, was named after an acronym. Can you guess what it stands for?",
            },
            {
                "title": "Write a draft announcement",
                "message": "Can you write a draft announcement about a new feature my team just released? It must include how impactful it is.",
            },
            {
                "title": "Suggest names for my Slack app",
                "message": "Can you suggest a few names for my Slack app? The app helps my teammates better organize information and plan priorities and action items.",
            },
        ]

        thread_context = get_thread_context()
        if thread_context is not None and thread_context.channel_id is not None:
            summarize_channel = {
                "title": "Summarize the referred channel",
                "message": "Can you generate a brief summary of the referred channel?",
            }
            prompts.append(summarize_channel)

        set_suggested_prompts(prompts=prompts)
    except Exception as e:
        logger.exception(f"Failed to handle an assistant_thread_started event: {e}", e)
        say(f":warning: Something went wrong! ({e})")


# This listener is invoked when the human user sends a reply in the assistant thread
@assistant.user_message
def respond_in_assistant_thread(
    payload: dict,
    logger: logging.Logger,
    context: BoltContext,
    client: WebClient,
    say: Say,
):
    try:
        user_id = payload["user"]
        channel_id = payload["channel"]
        thread_ts = payload["thread_ts"]

        loading_messages = [
            "Teaching the hamsters to type faster…",
            "Untangling the internet cables…",
            "Consulting the office goldfish…",
            "Polishing up the response just for you…",
            "Convincing the AI to stop overthinking…",
        ]

        replies = client.conversations_replies(
            channel=context.channel_id,
            ts=context.thread_ts,
            oldest=context.thread_ts,
            limit=10,
        )
        messages_in_thread: List[Dict[str, str]] = []
        for message in replies["messages"]:
            role = "user" if message.get("bot_id") is None else "assistant"
            messages_in_thread.append({"role": role, "content": message["text"]})

        returned_message = call_llm(messages_in_thread)

        client.assistant_threads_setStatus(
            channel_id=channel_id, thread_ts=thread_ts, status="Bolt is typing", loading_messages=loading_messages
        )

        stream_response = client.chat_startStream(
            channel=channel_id,
            thread_ts=thread_ts,
        )
        stream_ts = stream_response["ts"]

        # use of this for loop is specific to openai response method
        for event in returned_message:
            if event.type == "response.output_text.delta":
                client.chat_appendStream(channel=channel_id, ts=stream_ts, markdown_text=f"{event.delta}")
            else:
                continue

        feedback_block = create_feedback_block(user_id=user_id)
        client.chat_stopStream(channel=channel_id, ts=stream_ts, blocks=feedback_block)

    except Exception as e:
        logger.exception(f"Failed to handle a user message event: {e}")
        say(f":warning: Something went wrong! ({e})")


# Handle feedback buttons (thumbs up/down)
def handle_feedback(ack, body, client, logger):
    ack()
    try:
        message_ts = body["message"]["ts"]
        channel_id = body["channel"]["id"]
        feedback_type = body["actions"][0]["value"]
        is_positive = feedback_type == "good-feedback"

        if is_positive:
            client.chat_postEphemeral(
                channel=channel_id,
                user=body["user"]["id"],
                thread_ts=message_ts,
                text="We're glad you found this useful.",
            )
        else:
            client.chat_postEphemeral(
                channel=channel_id,
                user=body["user"]["id"],
                thread_ts=message_ts,
                text="Sorry to hear that response wasn't up to par :slightly_frowning_face: Starting a new chat may help with AI mistakes and hallucinations.",
            )

        logger.debug(f"Handled feedback: type={feedback_type}, message_ts={message_ts}")
    except Exception as error:
        logger.error(f":warning: Something went wrong! {error}")
