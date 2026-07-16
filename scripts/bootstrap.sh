#!/bin/bash

# Creates the S3 bucket and DynamoDB table used for the Terraform backend.

set -e

AWS_REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

BUCKET_NAME="ai-ops-tf-state-${ACCOUNT_ID}"
TABLE_NAME="ai-ops-tf-lock"

echo "Creating S3 bucket: ${BUCKET_NAME}"

if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket \
        --bucket "${BUCKET_NAME}"
else
    aws s3api create-bucket \
        --bucket "${BUCKET_NAME}" \
        --create-bucket-configuration LocationConstraint="${AWS_REGION}"
fi

aws s3api put-bucket-versioning \
    --bucket "${BUCKET_NAME}" \
    --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
    --bucket "${BUCKET_NAME}" \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        }
      }]
    }'

echo "Creating DynamoDB table: ${TABLE_NAME}"

aws dynamodb create-table \
    --table-name "${TABLE_NAME}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "${AWS_REGION}"

echo
echo "Terraform backend created successfully."
echo
echo "Bucket : ${BUCKET_NAME}"
echo "Table  : ${TABLE_NAME}" 