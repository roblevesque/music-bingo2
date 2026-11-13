# Configuration Variables
REGISTRY ?= ghcr.io
GITHUB_USER ?= your-github-username
IMAGE_NAME ?= your-repo-name
TAG ?= $(shell git rev-parse --short HEAD)

# Full image path (must be lowercase for ghcr.io)
FULL_IMAGE := $(shell echo "$(REGISTRY)/$(GITHUB_USER)/$(IMAGE_NAME)" | tr '[:upper:]' '[:lower:]')

.PHONY: help login build push release

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

login: ## Log in to GitHub Container Registry (requires CR_PAT env var)
	@echo "$$CR_PAT" | docker login $(REGISTRY) -u $(GITHUB_USER) --password-stdin

build: ## Build the Docker image locally
	docker build -t $(FULL_IMAGE):$(TAG) -t $(FULL_IMAGE):latest .

push: ## Push the tagged images to GitHub Container Registry
	docker push $(FULL_IMAGE):$(TAG)
	docker push $(FULL_IMAGE):latest

release: build push ## Build and push the image in one step