.PHONY: help init install-deps download-model bake-audio bake-audio-force list-audio clean-audio clean-model clean-all test run french-drift track-evil

PYTHON ?= .venv/bin/python
UV ?= $(shell which uv 2>/dev/null)
MODEL_DIR = assets/models
SOUND_DIR = assets/sound
MODEL_NAME = en_GB-alan-low
MODEL_URL = https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx
CONFIG_URL = https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json

help:
	@echo "Available commands in SimPad Makefile:"
	@echo "  make init             - Initialize complete development environment (deps, ONNX model, bake WAV, tests)"
	@echo "  make install-deps     - Install and synchronize Python dependencies"
	@echo "  make download-model   - Download Piper ONNX voice model ($(MODEL_NAME)) and config"
	@echo "  make bake-audio       - Generate missing audio WAV cue files"
	@echo "  make bake-audio-force - Force regeneration of all audio WAV cue files"
	@echo "  make list-audio       - Display audio cache status"
	@echo "  make clean-audio      - Remove generated WAV files from $(SOUND_DIR)"
	@echo "  make clean-model      - Remove ONNX model files from $(MODEL_DIR)"
	@echo "  make clean-all        - Remove all generated audio files and ONNX models"
	@echo "  make test             - Run unit test suite"
	@echo "  make run              - Launch SimPad application"
	@echo "  make french-drift     - Audit codebase for French language drift"
	@echo "  make track-evil       - Run OOP linter on codebase"

init: install-deps download-model bake-audio test
	@echo ""
	@echo "================================================================"
	@echo "  🎉 SimPad environment successfully initialized!"
	@echo "  • Virtual environment : .venv/"
	@echo "  • ONNX voice model    : $(MODEL_DIR)/$(MODEL_NAME).onnx"
	@echo "  • Audio cue files     : $(SOUND_DIR)/"
	@echo "  • Unit tests          : Passed"
	@echo ""
	@echo "  To launch the application:"
	@echo "    $(PYTHON) main_qt.py"
	@echo "================================================================"

install-deps:
	@echo "==> Installing / synchronizing dependencies..."
	@if [ -n "$(UV)" ]; then \
		echo "Using uv..."; \
		$(UV) sync --all-groups; \
	else \
		echo "Using python3 -m venv & pip..."; \
		python3 -m venv .venv; \
		$(PYTHON) -m pip install --upgrade pip; \
		$(PYTHON) -m pip install -e ".[dev]"; \
	fi

download-model:
	@mkdir -p $(MODEL_DIR)
	@if [ ! -f $(MODEL_DIR)/$(MODEL_NAME).onnx ]; then \
		echo "==> Downloading Piper ONNX voice model ($(MODEL_NAME).onnx)..."; \
		curl -L --progress-bar -o $(MODEL_DIR)/$(MODEL_NAME).onnx $(MODEL_URL); \
	else \
		echo "==> ONNX voice model already present: $(MODEL_DIR)/$(MODEL_NAME).onnx"; \
	fi
	@if [ ! -f $(MODEL_DIR)/$(MODEL_NAME).onnx.json ]; then \
		echo "==> Downloading configuration file ($(MODEL_NAME).onnx.json)..."; \
		curl -L --progress-bar -o $(MODEL_DIR)/$(MODEL_NAME).onnx.json $(CONFIG_URL); \
	else \
		echo "==> Configuration already present: $(MODEL_DIR)/$(MODEL_NAME).onnx.json"; \
	fi
	@echo "==> Piper model ready in $(MODEL_DIR)/"

bake-audio: download-model
	@echo "==> Generating audio files (WAV)..."
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py

bake-audio-force: download-model
	@echo "==> Forcing regeneration of all audio files (WAV)..."
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py --force

list-audio:
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py --list

clean-audio:
	@echo "==> Cleaning generated audio files in $(SOUND_DIR)..."
	@rm -f $(SOUND_DIR)/*.wav $(SOUND_DIR)/*.mp3
	@echo "==> Audio cleaned."

clean-model:
	@echo "==> Cleaning ONNX models in $(MODEL_DIR)..."
	@rm -f $(MODEL_DIR)/*.onnx $(MODEL_DIR)/*.onnx.json
	@echo "==> Models cleaned."

clean-all: clean-audio clean-model

test:
	@PYTHONPATH=. $(PYTHON) -m pytest tests/

run:
	@PYTHONPATH=. $(PYTHON) main_qt.py

french-drift:
	@PYTHONPATH=. $(PYTHON) scripts/french_drift.py

track-evil:
	@PYTHONPATH=. $(PYTHON) scripts/lint_oop_evil.py ./simpad_qt -s
