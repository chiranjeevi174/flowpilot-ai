-- Initialize test database for FlowPilot AI automated tests
SELECT 'CREATE DATABASE flowpilot_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'flowpilot_test')\gexec
