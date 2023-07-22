import datetime
import json
import os
from logging import getLogger

from pynamodb.attributes import UnicodeAttribute
from pynamodb.models import Model
from slack import WebClient

logger = getLogger(__name__)

slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
slack_channel_channel_id = os.getenv("SLACK_CHANNEL_CHANNEL_ID")
dynamodb_region = os.getenv("DYNAMODB_REGION")
dynamodb_channel_table_name = os.getenv("DYNAMODB_CHANNEL_TABLE_NAME")
jst = datetime.timezone(datetime.timedelta(hours=9))


class SlackChannel(Model):
    class Meta:
        table_name = dynamodb_channel_table_name
        region = dynamodb_region

    channel_id = UnicodeAttribute(hash_key=True)
    name = UnicodeAttribute()
    purpose = UnicodeAttribute()
    topic = UnicodeAttribute()
    update_at = UnicodeAttribute()


def post_new_channels():
    client = WebClient(token=slack_bot_token)
    current_date = datetime.datetime.now(tz=jst).strftime("%Y-%m-%dT%H:%M:%S%z")

    max_notify_count = 10

    # DynamoDBより登録済みchannel_idを取得
    registered_channel_ids = list(map(lambda c: c.channel_id, SlackChannel.scan()))

    # Slackより登録済みchannelを取得
    total_channels = []
    next_cursor = None
    while True:
        conversations = (
            client.conversations_list(cursor=next_cursor)
            if next_cursor
            else client.conversations_list()
        )
        assert conversations["ok"]

        total_channels += conversations["channels"]
        next_cursor = conversations["response_metadata"]["next_cursor"]

        if not next_cursor:
            break

    # Slackのchannelを走査し、通知対象を決定
    should_notify_channels = []
    for channel in total_channels:
        id = channel["id"]
        name = channel["name"]
        purpose = channel["purpose"]["value"]
        topic = channel["topic"]["value"]
        is_archived = channel["is_archived"]
        is_shared = channel["is_shared"]
        is_private = channel["is_private"]
        is_regular_only = name.startswith("reg")

        if (
            (id not in registered_channel_ids)
            and (not is_archived)
            and (not is_shared)
            and (not is_private)
            and (not is_regular_only)
        ):
            # DynamoDBに未登録のチャンネルの場合、通知対象とする
            slack_channel = SlackChannel(id)
            slack_channel.name = name
            slack_channel.purpose = purpose if purpose else ""
            slack_channel.topic = topic if topic else ""
            slack_channel.update_at = current_date
            should_notify_channels.append(slack_channel)

    # 通知対象が存在する場合
    if len(should_notify_channels) > 0:
        logger.warning(f"should notify channel count: {len(should_notify_channels)}")

        # DynamoDBに登録
        with SlackChannel.batch_write() as batch:
            for channel in should_notify_channels:
                batch.save(channel)

        # Slack通知
        notify_channels = []
        for c in should_notify_channels[:max_notify_count]:
            p = c.purpose.split("\n")[0]

            if len(p) == 0:
                p = c.topic.split("\n")[0]

            notify_channels.append(f"<#{c.channel_id}> {p}")
        notify_channels = sorted(notify_channels)

        message = "今日生まれた新しいチャンネルを紹介するね！！\n{}".format("\n".join(notify_channels))
        client.chat_postMessage(channel=slack_channel_channel_id, text=message)

        if len(should_notify_channels) > max_notify_count:
            message = "他にも{}個生まれたけど、他は自分で確認してね！".format(
                len(should_notify_channels) - max_notify_count
            )
            client.chat_postMessage(channel=slack_channel_channel_id, text=message)


def lambda_handler(event, _lambda_context):
    try:
        logger.info("start")
        logger.info(f"event: {json.dumps(event)}")

        post_new_channels()

    except Exception as e:
        logger.exception("fail")

        raise e


if __name__ == "__main__":
    logger.info("start")
    post_new_channels()
