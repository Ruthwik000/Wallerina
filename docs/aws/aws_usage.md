# AWS Services in Wallerina

AWS is used only where it provides a meaningful architectural benefit.  
The core quantitative logic remains inside Wallerina's backend; AWS provides the infrastructure for data, asynchronous workloads, security, and reliability.

| AWS Service | Where it is used | Purpose |
|---|---|---|
| **Amazon ECS / Fargate** | FastAPI Backend | Runs the Wallerina backend in a containerized environment without managing servers. |
| **Amazon RDS (PostgreSQL)** | Application Database | Stores users, wallets, portfolio snapshots, market data, risk metrics, simulations, and recommendations. |
| **Amazon S3** | Historical Data Storage | Stores large historical market-data and Polymarket datasets that are used by the quantitative engine. |
| **AWS Lambda** | Data Ingestion & Scheduled Jobs | Runs lightweight background tasks such as refreshing market data, Polymarket data, and portfolio snapshots. |
| **Amazon EventBridge** | Data Refresh Scheduling | Triggers Lambda jobs periodically to keep market and prediction-market data up to date. |
| **Amazon SQS** | Simulation Pipeline | Queues computationally expensive Monte Carlo jobs so the API does not have to wait for simulations to finish. |
| **AWS Secrets Manager** | API Credentials | Securely stores Alchemy, market-data, database, and other API credentials instead of exposing them in application code. |
| **Amazon CloudWatch** | Monitoring & Logging | Collects backend logs, Lambda errors, simulation failures, API latency, and infrastructure metrics. |

## Data Flow

```text
                         Wallerina Frontend
                                |
                                v
                       FastAPI on ECS/Fargate
                                |
              +-----------------+-----------------+
              |                 |                 |
              v                 v                 v
           Alchemy          Polymarket       Market APIs
              |                 |                 |
              +-----------------+-----------------+
                                |
                                v
                         PostgreSQL (RDS)
                                |
                                v
                     Wallerina Quant Engine
                       /                \
                      v                  v
                   Risk            Monte Carlo
                                         |
                                         v
                                        SQS
                                         |
                                         v
                                Simulation Worker
                                         |
                              +----------+----------+
                              |                     |
                              v                     v
                           RDS                  S3
                              |                     |
                              +----------+----------+
                                         |
                                         v
                                  Recommendation
                                         |
                                         v
                                  Wallerina UI