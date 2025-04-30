import json
import logging
import os
import requests
import csv
import io
from datetime import datetime, timezone, timedelta
import smtplib
from email.message import EmailMessage

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get New Relic credentials from environment variables
NEWRELIC_API_KEY = os.getenv('NEWRELIC_API_KEY')
NEWRELIC_ACCOUNT_ID = os.getenv('NEWRELIC_ACCOUNT_ID')
GMAIL_USER = os.getenv('GMAIL_USER')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')
RECEIVER_EMAILS = os.getenv('RECEIVER_EMAILS').split(',')
RECEIVER_CC = os.getenv('RECEIVER_CC')

if not NEWRELIC_API_KEY or not NEWRELIC_ACCOUNT_ID:
    logger.error("New Relic API key or Account ID is missing from environment variables")
    raise EnvironmentError("New Relic credentials are not set")

if not GMAIL_USER or not GMAIL_PASSWORD:
    logger.error("Gmail credentials are missing from environment variables")
    raise EnvironmentError("Gmail credentials are not set")

def clean_string(value):
    logger.debug(f"Cleaning string: {value}")
    if isinstance(value, str):
        return value.strip("[]")
    return value

def clean_request_body(request_body):
    logger.debug("Cleaning request body")
    return {key: clean_string(value) for key, value in request_body.items()}

def get_newrelic_errors(entity):
    logger.info(f"Now proceeding to fetch errors for entity name: {entity}")
    url = "https://api.eu.newrelic.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "API-Key": NEWRELIC_API_KEY
    }
    query = """
    query($accountId: Int!) {
      actor {
        account(id: $accountId) {
          nrql(query: "FROM ErrorTrace SELECT * WHERE appName = '%s' SINCE 60 MINUTES AGO LIMIT 1000") {
            results
          }
        }
      }
    }
    """ % entity

    variables = {
        "accountId": int(NEWRELIC_ACCOUNT_ID)
    }

    try:
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
        logger.debug(f"New Relic API Response Status Code: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        return data['data']['actor']['account']['nrql']['results']
    except requests.RequestException as e:
        logger.error(f"Error fetching data from New Relic: {e}")
        if e.response:
            logger.error(f"Response content: {e.response.text}")
        else:
            logger.error("No response content")
        return None

def convert_timestamp_to_ist(timestamp):
    utc_dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    ist_dt = utc_dt + timedelta(hours=5, minutes=30)
    return ist_dt.strftime('%Y-%m-%d %H:%M:%S')

def generate_csv_content(errors):
    logger.info("Generating CSV content for application errors")
    fieldnames = [
        "Timestamp", "Application Error Name", "appName", "code.filepath", "code.function",
        "code.lineno", "error.class", "error.message", "message", "path",
        "request.headers.host", "request.headers.referer", "request.uri",
        "response.status", "transactionName"
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for error in errors:
        writer.writerow({
            "Timestamp": convert_timestamp_to_ist(error.get("timestamp", "")),
            "Application Error Name": error.get("aggregateFacet", ""),
            "appName": error.get("appName", ""),
            "code.filepath": error.get("code.filepath", ""),
            "code.function": error.get("code.function", ""),
            "code.lineno": error.get("code.lineno", ""),
            "error.class": error.get("error.class", ""),
            "error.message": error.get("error.message", ""),
            "message": error.get("message", ""),
            "path": error.get("path", ""),
            "request.headers.host": error.get("request.headers.host", ""),
            "request.headers.referer": error.get("request.headers.referer", ""),
            "request.uri": error.get("request.uri", ""),
            "response.status": error.get("response.status", ""),
            "transactionName": error.get("transactionName", "")
        })
    
    return output.getvalue()

## Draft your APM Error Report Email
def send_email_with_csv(entity, created_at, csv_content): 
    current_date = datetime.now().strftime('%Y-%m-%d')
    subject = f"Clovia {entity} Application Error Logs Sheet for {convert_timestamp_to_ist(created_at)}"
    body = f"""
    Hi team,

    Please find attached the sheet containing "{entity}" Application Errors logs from Incident timeframe {convert_timestamp_to_ist(created_at)}.

    Regards,
    ........
    """

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(RECEIVER_EMAILS)  # Multiple recipients
    if RECEIVER_CC:
        msg['Cc'] = RECEIVER_CC
    msg.set_content(body)

    filename = f'Clovia-{entity}-Application-Error-{current_date}.csv'
    msg.add_attachment(csv_content.encode(), maintype='text', subtype='csv', filename=filename)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email sent successfully with attachment {filename}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

def lambda_handler(event, context):
    logger.info("Received NewRelic alert")
    logger.info(f"Received event: {event}")  # Log the entire event

    try:
        # Check if the event is already a dict
        if isinstance(event, dict):
            body = event
        else:
            # If not, try to parse it as JSON
            body = json.loads(event)
        
        logger.debug(f"Processed alert data: {body}")

        required_keys = {'impactedEntities', 'title', 'state', 'createdAt'}
        if not required_keys.issubset(body):
            logger.error(f"Missing required keys in payload: {required_keys - set(body.keys())}")
            return {
                "statusCode": 400,
                "body": json.dumps({"detail": "Invalid payload: missing required keys"})
            }

        impacted_entities = body['impactedEntities']
        title = body['title']
        state = body['state']
        created_at = body['createdAt']

        if state != "ACTIVATED":
            logger.info(f"Alert state is not 'ACTIVATED': {state}")
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Alert state is not 'ACTIVATED', ignoring."})
            }

### Input the APM name here:
        interested_entities = ["API", "WEB", "UI", "PROD"]  
        all_errors = []
        for entity in impacted_entities:
            if entity in interested_entities:
                logger.info(f"Processing entity: {entity}")
                errors = get_newrelic_errors(entity)
                if errors:
                    logger.info(f"Found {len(errors)} errors for {entity}")
                    all_errors.extend(errors)
                else:
                    logger.info(f"No errors found for {entity}")

        if all_errors:
            csv_content = generate_csv_content(all_errors)
            send_email_with_csv("-".join(impacted_entities), created_at, csv_content)
        else:
            logger.info("No errors found for any impacted entities")
        
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Alert processed successfully. Application Error Logs sheet has been generated and mail sent."})
        }
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return {
            "statusCode": 400,
            "body": json.dumps({"detail": "Invalid JSON"})
        }
    except KeyError as e:
        logger.error(f"Missing key in payload: {e}")
        return {
            "statusCode": 400,
            "body": json.dumps({"detail": f"Invalid payload: missing key {e}"})
        }
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"detail": "Internal server error"})
        }

if __name__ == "__main__":
    logger.info("Starting the application")
    # Uncomment below line to run locally
    # uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
