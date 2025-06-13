#!/bin/bash

set -e

cd "$(dirname "$0")"

for test_file in test/*.py; do
    echo "running $test_file..."
    .venv/bin/python "$test_file"
done