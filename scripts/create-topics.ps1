he# Creates the 3 VelocityFraud Kafka topics inside the running vf-kafka container.
# Run from the velocityfraud root: .\scripts\create-topics.ps1

$ErrorActionPreference = "Stop"

$container = "vf-kafka"
$bootstrap = "localhost:9092"
$kafkaTopics = "/opt/kafka/bin/kafka-topics.sh"

$topics = @(
    @{ name = "transactions.raw";          partitions = 3; retentionMs = 604800000 },  # 7 days
    @{ name = "transactions.scored";       partitions = 3; retentionMs = 86400000  },  # 1 day
    @{ name = "transactions.enriched";     partitions = 1; retentionMs = 604800000 },  # 7 days
    @{ name = "transactions.scored.groq";  partitions = 1; retentionMs = 86400000  },  # 1 day (Layer 5b)
    @{ name = "transactions.feedback";      partitions = 1; retentionMs = 2592000000 } # 30 days (analyst verdicts / retraining labels)
)

foreach ($t in $topics) {
    Write-Host "Creating topic $($t.name) ..." -ForegroundColor Cyan
    docker exec $container $kafkaTopics `
        --create `
        --if-not-exists `
        --topic $t.name `
        --bootstrap-server $bootstrap `
        --partitions $t.partitions `
        --replication-factor 1 `
        --config "retention.ms=$($t.retentionMs)"
}

Write-Host "`nCurrent topic list:" -ForegroundColor Green
docker exec $container $kafkaTopics --list --bootstrap-server $bootstrap
