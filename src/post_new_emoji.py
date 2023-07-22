import datetime
import json
import os
from logging import getLogger

from pynamodb.attributes import UnicodeAttribute
from pynamodb.models import Model
from slack import WebClient

logger = getLogger(__name__)

slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
slack_emoji_channel_id = os.getenv("SLACK_EMOJI_CHANNEL_ID")
dynamodb_region = os.getenv("DYNAMODB_REGION")
dynamodb_emoji_table_name = os.getenv("DYNAMODB_EMOJI_TABLE_NAME")
jst = datetime.timezone(datetime.timedelta(hours=9))


class SlackEmoji(Model):
    class Meta:
        table_name = dynamodb_emoji_table_name
        region = dynamodb_region

    name = UnicodeAttribute(hash_key=True)
    url = UnicodeAttribute()
    update_at = UnicodeAttribute()


def post_new_emojies():
    client = WebClient(token=slack_bot_token)
    current_date = datetime.datetime.now(tz=jst).strftime("%Y-%m-%dT%H:%M:%S%z")

    max_notify_count = 10

    # DynamoDBより登録済みemoji名を取得
    registered_emoji_names = list(map(lambda e: e.name, SlackEmoji.scan()))

    # Slackより登録済みemojiを取得
    emojies = client.emoji_list()
    assert emojies["ok"]

    # Slackのemojiを走査し、通知対象を決定
    should_notify_emojies = []
    for name, url in emojies["emoji"].items():
        if (name not in registered_emoji_names) and url.startswith("https:"):
            # DynamoDBに未登録のemojiの場合、通知対象とする
            slack_emoji = SlackEmoji(name)
            slack_emoji.url = url
            slack_emoji.update_at = current_date
            should_notify_emojies.append(slack_emoji)

    # 通知対象が存在する場合
    if len(should_notify_emojies) > 0:
        logger.warning(f"should notify emoji count: {len(should_notify_emojies)}")

        # DynamoDBに登録
        with SlackEmoji.batch_write() as batch:
            for emoji in should_notify_emojies:
                batch.save(emoji)

        # Slack通知
        for emoji in should_notify_emojies[:max_notify_count]:
            message = "新しいemojiが追加されたよ！！\n`:{}:` {}".format(emoji.name, emoji.url)
            client.chat_postMessage(channel=slack_emoji_channel_id, text=message)

        if len(should_notify_emojies) > max_notify_count:
            message = "他にも{}個追加されてたけど、他は自分で確認してね！".format(
                len(should_notify_emojies) - max_notify_count
            )
            client.chat_postMessage(channel=slack_emoji_channel_id, text=message)


def lambda_handler(event, _lambda_context):
    try:
        logger.info("start")
        logger.info(f"event: {json.dumps(event)}")

        post_new_emojies()

    except Exception as e:
        logger.exception("fail")

        raise e


if __name__ == "__main__":
    logger.info("start")
    post_new_emojies()
