terraform {
  backend "s3" {
    bucket         = "ai-ops-serverless-tfstate-678632990341"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "ai-ops-serverless-tflock"
  }
}
