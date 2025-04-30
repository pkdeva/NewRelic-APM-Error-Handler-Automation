# New Relic APM Error Alert Handler

This repository contains an automated script that listens for alerts from New Relic APM, fetches recent error traces for impacted services, and sends them via email in a CSV report format.

## Features

- Listens to New Relic webhook alert payloads (ideal for AWS Lambda or Flask app).
- Fetches recent errors (last 60 minutes) for selected applications using New Relic's GraphQL API.
- Generates a detailed CSV report of error traces.
- Sends the report via email using Gmail SMTP.
- Cleans and formats data before sending.

## Requirements

- Python 3.8+
- Gmail SMTP credentials
- New Relic API key and Account ID
- Pre-configured environment variables

## Environment Variables

| Variable            | Description                                 |
|---------------------|---------------------------------------------|
| `NEWRELIC_API_KEY`  | New Relic User API Key                      |
| `NEWRELIC_ACCOUNT_ID` | Your New Relic Account ID                |
| `GMAIL_USER`        | Gmail address to send emails from           |
| `GMAIL_PASSWORD`    | Gmail App Password (not your account password) |
| `RECEIVER_EMAILS`   | Comma-separated list of recipient emails    |
| `RECEIVER_CC`       | (Optional) CC email address                 |

## Flow Diagram

```mermaid
flowchart TD
    A[New Relic Alert Triggered] --> B[Webhook Payload Received]
    B --> C[Check if alert is ACTIVATED]
    C -- No --> Z[Ignore and exit]
    C -- Yes --> D[Parse impactedEntities]
    D --> E[Call New Relic GraphQL API for each entity]
    E --> F[Fetch recent ErrorTrace events]
    F --> G[Generate CSV from error data]
    G --> H[Send email via SMTP with CSV attachment]
    H --> I[Log success or failure]
