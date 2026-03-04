.PHONY: verify test-compositor

verify:
	@echo "Running compositor verification..."
	bash scripts/test_compositor_integration.sh

test-compositor:
	@echo "Running compositor integration test for books 1, 9, 25..."
	bash scripts/test_compositor_integration.sh 1
	bash scripts/test_compositor_integration.sh 9
	bash scripts/test_compositor_integration.sh 25
	@echo "All books passed verification."
