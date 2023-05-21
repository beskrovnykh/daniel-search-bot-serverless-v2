from datetime import date, timedelta

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError


class UserRequestsDao:
    def __init__(self):
        self.table_name = "user_requests"
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(self.table_name)

    def get_user_requests_count(self, user_id):
        try:
            current_date = date.today()
            current_date = current_date + timedelta(days=1)  # added for feature testing

            current_date_iso_format = current_date.isoformat()

            filter_expression = Key('user_id').eq(str(user_id)) & Attr('last_accessed_date').eq(current_date_iso_format)

            projection_expression = 'requests_count, last_accessed_date'

            response = self.table.scan(FilterExpression=filter_expression, ProjectionExpression=projection_expression)

            items = response.get('Items', [])
            if items:
                request_count = items[0].get('requests_count', 0)
                return request_count
            else:
                return 0
        except ClientError as e:
            print(f"Error retrieving user requests count: {e.response['Error']['Message']}")
            return 0

    def update_user_requests_count(self, user_id):
        try:
            current_date = date.today()
            current_date = current_date + timedelta(days=1)  # added for feature testing

            current_date_iso_format = current_date.isoformat()

            response = self.table.update_item(
                Key={'user_id': str(user_id)},
                UpdateExpression='SET requests_count = if_not_exists(requests_count, :start) + :inc, '
                                 'last_accessed_date = :date '
                                 'ADD requests_count_zeroed',
                ExpressionAttributeValues={':inc': 1, ':start': 0, ':date': current_date_iso_format},
                ReturnValues='ALL_NEW'
            )
            return response.get('Attributes', {})
        except ClientError as e:
            print(f"Error updating user requests count: {e.response['Error']['Message']}")
            return None
