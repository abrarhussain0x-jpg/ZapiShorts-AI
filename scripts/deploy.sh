#!/bin/bash

# ZAPI Enterprise Deployment Script
# This script sets up the entire ZAPI system with all services

set -e

echo "=========================================="
echo "ZAPI Enterprise System Setup"
echo "=========================================="
echo ""

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"
    
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker is not installed${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker found${NC}"
    
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}❌ Docker Compose is not installed${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Docker Compose found${NC}"
    
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Python 3 is not installed${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Python 3 found${NC}"
    echo ""
}

# Setup environment
setup_environment() {
    echo -e "${YELLOW}Setting up environment...${NC}"
    
    if [ ! -f ".env" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ Created .env from template${NC}"
        echo -e "${YELLOW}⚠️  Please edit .env with your configuration${NC}"
        echo "   Required: YOUTUBE_API_KEY, FACEBOOK_ACCESS_TOKEN, FACEBOOK_PAGE_ID"
    else
        echo -e "${GREEN}✓ .env already exists${NC}"
    fi
    echo ""
}

# Create directories
create_directories() {
    echo -e "${YELLOW}Creating directories...${NC}"
    
    mkdir -p data/downloads data/output data/logs data/temp
    echo -e "${GREEN}✓ Data directories created${NC}"
    echo ""
}

# Build Docker images
build_images() {
    echo -e "${YELLOW}Building Docker images...${NC}"
    docker-compose build
    echo -e "${GREEN}✓ Images built successfully${NC}"
    echo ""
}

# Start services
start_services() {
    echo -e "${YELLOW}Starting services...${NC}"
    
    docker-compose up -d postgres redis
    echo -e "${GREEN}✓ Database and cache started${NC}"
    
    sleep 5
    
    echo -e "${YELLOW}Initializing database...${NC}"
    docker-compose run --rm api python scripts/init_db.py
    echo -e "${GREEN}✓ Database initialized${NC}"
    
    docker-compose up -d api celery_worker celery_beat flower
    echo -e "${GREEN}✓ All services started${NC}"
    echo ""
}

# Check health
check_health() {
    echo -e "${YELLOW}Checking service health...${NC}"
    
    sleep 5
    
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ API is healthy${NC}"
    else
        echo -e "${RED}❌ API is not responding${NC}"
        return 1
    fi
    
    if docker-compose ps celery_worker | grep -q "Up"; then
        echo -e "${GREEN}✓ Celery worker is running${NC}"
    else
        echo -e "${RED}❌ Celery worker is not running${NC}"
        return 1
    fi
    echo ""
}

# Print info
print_info() {
    echo -e "${GREEN}=========================================="
    echo "ZAPI Enterprise System is Running!"
    echo "==========================================${NC}"
    echo ""
    echo -e "API Documentation:  ${YELLOW}http://localhost:8000/api/docs${NC}"
    echo -e "ReDoc:              ${YELLOW}http://localhost:8000/api/redoc${NC}"
    echo -e "Health Check:       ${YELLOW}http://localhost:8000/health${NC}"
    echo -e "Flower (Monitoring):${YELLOW}http://localhost:5555${NC}"
    echo ""
    echo "Services Running:"
    docker-compose ps
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "1. Edit .env with your YouTube and Facebook credentials"
    echo "2. Visit http://localhost:8000/api/docs to explore API"
    echo "3. Use /api/queue/submit endpoints to start jobs"
    echo "4. Monitor jobs at http://localhost:5555"
    echo ""
    echo "Logs:"
    echo "  API logs:    docker-compose logs -f api"
    echo "  Worker logs: docker-compose logs -f celery_worker"
    echo "  All logs:    docker-compose logs -f"
    echo ""
}

# Main execution
main() {
    check_prerequisites
    setup_environment
    create_directories
    
    read -p "Build Docker images? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        build_images
    fi
    
    read -p "Start services? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        start_services
        check_health
        print_info
    fi
}

# Run main
main
