.PHONY: help init install-deps download-model bake-audio bake-audio-force list-audio clean-audio clean-model clean-all test run

PYTHON ?= .venv/bin/python
UV ?= $(shell which uv 2>/dev/null)
MODEL_DIR = assets/models
SOUND_DIR = assets/sound
MODEL_NAME = en_GB-alan-low
MODEL_URL = https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx
CONFIG_URL = https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json

help:
	@echo "Commandes disponibles dans SimPad Makefile :"
	@echo "  make init             - Initialise l'environnement complet pour un nouveau dev (deps, modèle ONNX, bake WAV, tests)"
	@echo "  make install-deps     - Installe/synchronise les dépendances Python"
	@echo "  make download-model   - Télécharge le modèle ONNX Piper ($(MODEL_NAME)) et sa config"
	@echo "  make bake-audio       - Génère les fichiers audio WAV manquants"
	@echo "  make bake-audio-force - Force la régénération de tous les fichiers audio WAV"
	@echo "  make list-audio       - Affiche l'état des fichiers audio"
	@echo "  make clean-audio      - Supprime les fichiers WAV générés dans $(SOUND_DIR)"
	@echo "  make clean-model      - Supprime le modèle ONNX dans $(MODEL_DIR)"
	@echo "  make clean-all        - Supprime les fichiers audio WAV et le modèle ONNX"
	@echo "  make test             - Lance la suite de tests unitaires"
	@echo "  make run              - Lance l'application SimPad"

init: install-deps download-model bake-audio test
	@echo ""
	@echo "================================================================"
	@echo "  🎉 Environnement SimPad initialisé avec succès !"
	@echo "  • Environnement virtuel : .venv/"
	@echo "  • Modèle ONNX           : $(MODEL_DIR)/$(MODEL_NAME).onnx"
	@echo "  • Fichiers audio WAV    : $(SOUND_DIR)/"
	@echo "  • Tests unitaires       : Validés"
	@echo ""
	@echo "  Pour lancer l'application :"
	@echo "    $(PYTHON) main_qt.py"
	@echo "================================================================"

install-deps:
	@echo "==> Installation / synchronisation des dépendances..."
	@if [ -n "$(UV)" ]; then \
		echo "Utilisation de uv..."; \
		$(UV) sync --all-groups; \
	else \
		echo "Utilisation de python3 -m venv & pip..."; \
		python3 -m venv .venv; \
		$(PYTHON) -m pip install --upgrade pip; \
		$(PYTHON) -m pip install -e ".[dev]"; \
	fi

download-model:
	@mkdir -p $(MODEL_DIR)
	@if [ ! -f $(MODEL_DIR)/$(MODEL_NAME).onnx ]; then \
		echo "==> Téléchargement du modèle ONNX Piper ($(MODEL_NAME).onnx)..."; \
		curl -L --progress-bar -o $(MODEL_DIR)/$(MODEL_NAME).onnx $(MODEL_URL); \
	else \
		echo "==> Modèle ONNX déjà présent : $(MODEL_DIR)/$(MODEL_NAME).onnx"; \
	fi
	@if [ ! -f $(MODEL_DIR)/$(MODEL_NAME).onnx.json ]; then \
		echo "==> Téléchargement du fichier de configuration ($(MODEL_NAME).onnx.json)..."; \
		curl -L --progress-bar -o $(MODEL_DIR)/$(MODEL_NAME).onnx.json $(CONFIG_URL); \
	else \
		echo "==> Configuration déjà présente : $(MODEL_DIR)/$(MODEL_NAME).onnx.json"; \
	fi
	@echo "==> Modèle Piper prêt dans $(MODEL_DIR)/"

bake-audio: download-model
	@echo "==> Génération des fichiers audio (WAV)..."
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py

bake-audio-force: download-model
	@echo "==> Régénération forcée de tous les fichiers audio (WAV)..."
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py --force

list-audio:
	@PYTHONPATH=. $(PYTHON) scripts/bake_audio.py --list

clean-audio:
	@echo "==> Nettoyage des fichiers audio générés dans $(SOUND_DIR)..."
	@rm -f $(SOUND_DIR)/*.wav $(SOUND_DIR)/*.mp3
	@echo "==> Audio nettoyé."

clean-model:
	@echo "==> Nettoyage des modèles ONNX dans $(MODEL_DIR)..."
	@rm -f $(MODEL_DIR)/*.onnx $(MODEL_DIR)/*.onnx.json
	@echo "==> Modèles nettoyés."

clean-all: clean-audio clean-model

test:
	@PYTHONPATH=. $(PYTHON) -m pytest tests/

run:
	@PYTHONPATH=. $(PYTHON) main_qt.py


track-evil:
	@PYTHONPATH=. $(PYTHON) scripts/lint_oop_evil.py ./simpad_qt
