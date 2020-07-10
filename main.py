# coding: utf-8
from urllib.parse import urlparse
import socks
import time
from telethon import TelegramClient, sync, events
from telethon.sessions import StringSession
from telethon import errors
import logging
import argparse
import boto3
import asyncio
from boto3.dynamodb.conditions import Key

DEFAULT_CLIENT_NAME = 'smsReceiver'


class TelegramMsgReceiver(object):

    def __init__(self, session, api_id, api_hash, sms_sign, proxy=None, logger=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.sms_sign = sms_sign

        if logger is None:
            self.logger = logging.getLogger(__name__)

        proxy_arr = None
        if proxy is not None:
            url_info = urlparse(proxy)
            domain = url_info.netloc.split(':')
            proxy_arr = (socks.PROXY_TYPES[url_info.scheme.upper()], domain[0], int(domain[1]))

        self.client = TelegramClient(StringSession(session),
                                     api_id=api_id,
                                     api_hash=api_hash,
                                     proxy=proxy_arr
                                     )

        self.chat = None

    async def start(self):
        await self.client.start()

    async def set_chat(self, chat):
        self.chat = await self.client.get_input_entity(chat)

    async def receive_top_msg(self, search=None):
        if self.chat is None:
            return None
        messages = await self.client.get_messages(self.chat, search=search)
        if len(messages) > 0:
            return messages[0]
        return None


class DynamoDB(object):

    def __init__(self, table_name='TgSmsMsg', dynamo_db=None):
        if dynamo_db is None:
            self.dynamo_db = boto3.resource('dynamodb', region_name='ap-southeast-1')
        else:
            self.dynamo_db = dynamo_db
        self.table_name = table_name
        self.create_table()
        self.table = self.dynamo_db.Table(self.table_name)

    def create_table(self):
        try:
            table = self.dynamo_db.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {
                        'AttributeName': 'msg_id',
                        'KeyType': 'HASH'  # Partition key
                    },
                    {
                        'AttributeName': 'date',
                        'KeyType': 'RANGE'  # Sort key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'msg_id',
                        'AttributeType': 'N'
                    },
                    {
                        'AttributeName': 'date',
                        'AttributeType': 'N'
                    }

                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 10,
                    'WriteCapacityUnits': 10
                }
            )
            return table
        except Exception as e:
            pass

    def query(self, msg_id):
        response = self.table.query(
            KeyConditionExpression=Key('msg_id').eq(msg_id)
        )
        return response['Items']

    def put(self, msg):
        # print(msg.id, msg.date, msg.text)
        if msg is None:
            return
        response = self.table.put_item(
            Item={
                'msg_id': msg.id,
                'date': int(msg.date.timestamp()),
                'text': msg.text
            }
        )
        return response


def init_argument_parser(parser):
    parser.add_argument('-p', '-proxy', '--proxy', help='use proxy', metavar="proxy url")
    parser.add_argument('-session', '--session', required=True, help='session', metavar="session")
    parser.add_argument('-api-id', '--api-id', required=True, help='api id', metavar="api id")
    parser.add_argument('-api-hash', '--api-hash', required=True, help='api hash', metavar="api hash")
    parser.add_argument('-c', '-chat', '--chat', required=True, help='chat', metavar="chat")
    parser.add_argument('-s', '-sms-sign', '--sms-sign', required=True, help='sms sign', metavar="sms sign")


async def main():
    parser = argparse.ArgumentParser()
    init_argument_parser(parser)

    args = parser.parse_args()
    receiver = TelegramMsgReceiver(args.session, args.api_id, args.api_hash, args.sms_sign, proxy=args.proxy)
    await receiver.start()
    await receiver.set_chat(args.chat)
    database = DynamoDB()
    count = 0
    while count < (60/12*58):
        msg = await receiver.receive_top_msg(args.sms_sign)
        database.put(msg)
        time.sleep(5)
        count = count + 1


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
