#!/bin/bash
# Headless E2E Validation Script for Multi-Agent Orchestrator
# This script runs all E2E scenario tests to ensure system-wide stability.

set -e

echo "🔍 Starting Headless E2E Validation Suite..."
export PYTHONPATH=$PYTHONPATH:.

# Run all tests in the tests/e2e directory
pytest -v tests/e2e/

echo "✅ All E2E scenarios passed successfully!"
