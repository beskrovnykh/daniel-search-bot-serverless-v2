import logging
from datetime import date, timedelta, datetime

import boto3
from botocore.exceptions import ClientError
from dateutil.parser import parse


class UserAnalyticsDao:
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table("user_analytics")

    def get_active_users_count(self, days=30):
        now = datetime.now()
        cutoff = now - timedelta(days=days)

        response = self.table.scan()  # todo: slow

        active_users_count = 0
        for item in response['Items']:
            last_seen = parse(item['last_seen'])
            if last_seen > cutoff:
                active_users_count += 1

        return active_users_count

    def get_total_users_count(self):
        response = self.table.scan()  # todo: slow
        return len(response['Items'])

    def user_exists(self, user_id):
        try:
            response = self.table.get_item(
                Key={
                    'user_id': str(user_id)
                }
            )
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            return 'Item' in response

    def register_user(self, user_id):
        now = datetime.now()
        try:
            self.table.put_item(
                Item={
                    'user_id': str(user_id),
                    'first_seen': str(now.isoformat()),
                    'last_seen': str(now.isoformat())
                }
            )
        except ClientError as e:
            print(e.response['Error']['Message'])

    def update_last_seen(self, user_id):
        try:
            self.table.update_item(
                Key={
                    'user_id': str(user_id)
                },
                UpdateExpression="set last_seen = :t",
                ExpressionAttributeValues={
                    ':t': str(datetime.now().isoformat())
                },
                ReturnValues="UPDATED_NEW"
            )
        except ClientError as e:
            print(e.response['Error']['Message'])


class UserRequestsDao:
    def __init__(self):
        self.table_name = "user_requests"
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(self.table_name)

    def reset_user_requests_count(self, user_id):
        try:
            current_date = date.today()
            # current_date = current_date + timedelta(days=1)  # added for feature testing

            current_date_iso_format = current_date.isoformat()

            self.table.update_item(
                Key={'user_id': str(user_id)},
                UpdateExpression='SET requests_count = :count, last_accessed_date = :date',
                ExpressionAttributeValues={':count': 0, ':date': current_date_iso_format}
            )
        except ClientError as e:
            logging.info(f"Error resetting user requests count: {e.response['Error']['Message']}")

    def get_user_requests_count(self, user_id):
        try:
            current_date = date.today()
            # current_date = current_date + timedelta(days=1)  # added for feature testing

            current_date_iso_format = current_date.isoformat()

            response = self.table.get_item(Key={'user_id': str(user_id)})
            item = response.get('Item')

            if item:
                last_accessed_date = item.get('last_accessed_date')
                if last_accessed_date != current_date_iso_format:
                    self.reset_user_requests_count(user_id)

                    response = self.table.get_item(Key={'user_id': str(user_id)})
                    item = response.get('Item')

                return item.get('requests_count', 0)
            else:
                return 0
        except ClientError as e:
            logging.info(f"Error retrieving user requests count: {e.response['Error']['Message']}")
            return 0

    def update_user_requests_count(self, user_id):
        try:
            current_date = date.today()
            # current_date = current_date + timedelta(days=1)  # added for feature testing

            current_date_iso_format = current_date.isoformat()

            response = self.table.update_item(
                Key={'user_id': str(user_id)},
                UpdateExpression='SET requests_count = if_not_exists(requests_count, :start) + :inc, '
                                 'last_accessed_date = :date',
                ExpressionAttributeValues={':inc': 1, ':start': 0, ':date': current_date_iso_format},
                ReturnValues='ALL_NEW'
            )
            return response.get('Attributes', {})
        except ClientError as e:
            logging.info(f"Error updating user requests count: {e.response['Error']['Message']}")
            return None
