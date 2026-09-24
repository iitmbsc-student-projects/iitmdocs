#!/bin/bash
# GCE VM startup script - runs on first boot
# Installs Docker, Weaviate, and Ollama with the embedding model

set -e

echo "=== IITM Chatbot GCE Startup Script ==="

# Install Docker
echo "Installing Docker..."
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# Install Docker Compose plugin
echo "Installing Docker Compose..."
apt-get update
apt-get install -y docker-compose-plugin

# Create app directory
echo "Creating app directory..."
mkdir -p /opt/iitm-chatbot
cd /opt/iitm-chatbot

# Create docker-compose.yml
echo "Creating docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.27.0
    restart: always
    command: --host 0.0.0.0 --port 8080 --scheme http --write-timeout=900s --read-timeout=900s
    ports:
      - "8080:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'
      PERSISTENCE_DATA_PATH: '/var/lib/weaviate'
      DEFAULT_VECTORIZER_MODULE: 'text2vec-ollama'
      ENABLE_MODULES: 'text2vec-ollama'
      OLLAMA_API_ENDPOINT: 'http://ollama:11434'
      MODULES_CLIENT_TIMEOUT: '600s'
    volumes:
      - ./weaviate_data:/var/lib/weaviate
    depends_on:
      - ollama

  ollama:
    image: ollama/ollama:latest
    restart: always
    ports:
      - "11434:11434"
    volumes:
      - ./ollama_data:/root/.ollama
EOF

# Start services
echo "Starting Docker services..."
docker compose up -d

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
sleep 30

# Pull embedding model
echo "Pulling bge-m3 model..."
docker exec $(docker ps -qf "name=ollama") ollama pull bge-m3

echo "=== GCE Startup Complete ==="
echo "Weaviate available at: http://$(curl -s ifconfig.me):8080"
echo "Ollama available at: http://$(curl -s ifconfig.me):11434"
