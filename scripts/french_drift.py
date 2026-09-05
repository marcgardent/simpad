#!/usr/bin/env python3
"""
SimPulse — French Drift Detection Script.
Scans Python and codebase source files to flag French vocabulary, docstrings, comments, and strings.
"""

from __future__ import annotations
import os
import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass, field

# Common French stop words (lowercase)
FRENCH_STOP_WORDS: Set[str] = {
    # Articles, prepositions, conjunctions, pronouns
    "le", "la", "les", "des", "du", "un", "une", "pour", "dans", "avec", "sur", "sous",
    "par", "vers", "sans", "chez", "mais", "donc", "que", "qui", "quoi", "dont",
    "est", "sont", "cette", "ces", "cet", "tous", "tout", "toutes", "toute", "comme",
    "aussi", "autre", "autres", "meme", "leur", "leurs", "notre", "votre", "nous", "vous",
    "ils", "elles", "afin", "ainsi", "alors", "après", "apres", "avant", "bien", "ceci",
    "cela", "celle", "celui", "ceux", "celles", "chaque", "depuis", "entre", "faire",
    "fait", "jusque", "lors", "moins", "plus", "pourquoi", "quand", "quel", "quelle",
    "quels", "quelles", "rien", "selon", "si", "seulement", "sous", "tant", "toujours",
    "tres", "trop",

    # Common domain/code vocabulary in French
    "vitesse", "rapport", "donnees", "données", "trame", "trames", "accelerateur", "accélérateur",
    "frein", "freinage", "pedale", "pedales", "pédale", "pédales", "telemetrie", "télémétrie",
    "onglet", "onglets", "etat", "etats", "état", "états", "initialisation", "generateur", "générateur",
    "mise", "jour", "fichier", "fichiers", "dossier", "dossiers", "introuvable", "reglage", "reglages",
    "réglage", "réglages", "debit", "débit", "frequence", "fréquence", "paquet", "paquets",
    "fermer", "ouvrir", "afficher", "masquer", "supprimer", "creer", "créer", "modifier",
    "activer", "desactiver", "désactiver", "sauvegarder", "enregistrer", "gestionnaire",
    "valeur", "valeurs", "chaine", "chaîne", "calcul", "virage", "course", "piste", "pilote",
    "ecurie", "écurie", "voiture", "tableau", "compteur", "jauge", "jauges", "affichage",
    "fenetre", "fenêtre", "reception", "réception", "envoi", "flux", "arret", "arrêt",
    "temps", "seconde", "secondes", "heure", "heures", "secteur", "secteurs",
    "reglement", "règlement", "drapeau", "drapeaux", "intermédiaire", "intermediaire"
}

# Regex for words containing French accented characters
ACCENTED_FRENCH_WORD_RE = re.compile(
    r"\b[a-zA-ZÀ-ÿ]*[éèêëàâäôöûüùçîïÉÈÊËÀÂÄÔÖÛÜÙÇÎÏ][a-zA-ZÀ-ÿ]*\b",
    re.IGNORECASE
)

# Regex for word tokenization
WORD_RE = re.compile(r"\b[a-zA-ZÀ-ÿ_]{2,}\b")

# Default ignore patterns
IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".idea",
    ".antigravitycli", "build", "dist", "simpulse.egg-info", "assets"
}

IGNORE_FILES = {
    "french_drift.py", "lint_oop_evil.py"
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyd", ".so", ".dll", ".zip", ".tar", ".gz", ".png", ".jpg",
    ".jpeg", ".ico", ".ttf", ".woff", ".wav", ".mp3", ".onnx", ".lock"
}


@dataclass
class MatchLocation:
    line_number: int
    matched_word: str
    line_content: str


@dataclass
class FileDriftReport:
    file_path: Path
    matches: List[MatchLocation] = field(default_factory=list)

    @property
    def total_occurrences(self) -> int:
        return len(self.matches)

    @property
    def unique_words(self) -> Set[str]:
        return {m.matched_word.lower() for m in self.matches}


def is_french_word(word: str) -> bool:
    """Check if a word matches French stop words, accented patterns, or French vocabulary."""
    cleaned = word.lower().strip()
    if len(cleaned) < 2:
        return False

    # Check direct dictionary lookup
    if cleaned in FRENCH_STOP_WORDS:
        return True

    # Check accented French characters (excluding common false positives like resume, naive)
    if ACCENTED_FRENCH_WORD_RE.search(word):
        return True

    return False


TECHNICAL_EXCLUSIONS = {
    "sans-serif", "sans_serif", "Le Mans Ultimate", "Le Mans", "Circuit de la Sarthe", "safety car"
}


def scan_file(file_path: Path) -> FileDriftReport:
    """Scan a single source file for French word occurrences."""
    report = FileDriftReport(file_path=file_path)

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return report

    lines = content.splitlines()
    for line_idx, line in enumerate(lines, start=1):
        # Skip pure hashbang / encoding comments
        if line_idx == 1 and line.startswith(("#!", "# -*-")):
            continue

        # Ignore technical exclusions case-insensitively
        cleaned_line = line
        for exc in TECHNICAL_EXCLUSIONS:
            cleaned_line = re.sub(re.escape(exc), " ", cleaned_line, flags=re.IGNORECASE)

        words = WORD_RE.findall(cleaned_line)
        for w in words:
            # Strip underscores (e.g. from variable names or snake_case)
            subwords = [sw for sw in re.split(r"[_\s]+", w) if sw]
            for sw in subwords:
                if is_french_word(sw):
                    report.matches.append(
                        MatchLocation(
                            line_number=line_idx,
                            matched_word=sw,
                            line_content=line.strip()
                        )
                    )
                    break  # Flag at most once per line or continue

    return report


def scan_directory(root_dir: Path, target_extensions: Set[str]) -> List[FileDriftReport]:
    """Recursively scan directory for files with target extensions."""
    reports: List[FileDriftReport] = []

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for fname in files:
            if fname in IGNORE_FILES:
                continue
            fpath = Path(root) / fname
            if fpath.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            if target_extensions and fpath.suffix.lower() not in target_extensions:
                if fpath.name != "Makefile":
                    continue

            rep = scan_file(fpath)
            if rep.total_occurrences > 0:
                reports.append(rep)

    return sorted(reports, key=lambda r: str(r.file_path))


def print_cli_report(reports: List[FileDriftReport], project_root: Path, verbose: bool = True) -> None:
    """Format and print detailed CLI report of French drift in the codebase."""
    total_files = len(reports)
    total_occurrences = sum(r.total_occurrences for r in reports)
    all_unique_words = set().union(*(r.unique_words for r in reports)) if reports else set()

    print("=" * 80)
    print(" 🇫🇷 SIMPULSE — FRENCH DRIFT AUDIT REPORT")
    print("=" * 80)
    print(f" Flagged Files       : {total_files}")
    print(f" Total Occurrences   : {total_occurrences}")
    print(f" Unique French Words : {len(all_unique_words)}")
    print("=" * 80)

    if not reports:
        print("\n✨ Clean! No French drift detected in scanned files.\n")
        return

    print("\n📁 DETAILED FILE BREAKDOWN:\n")

    for rep in reports:
        try:
            rel_path = rep.file_path.relative_to(project_root)
        except ValueError:
            rel_path = rep.file_path

        print(f"📄 {rel_path}  ({rep.total_occurrences} occurrences)")
        words_preview = ", ".join(sorted(rep.unique_words)[:8])
        if len(rep.unique_words) > 8:
            words_preview += f" ... (+{len(rep.unique_words) - 8} more)"
        print(f"   Words: [{words_preview}]")

        if verbose:
            # Print first 5 line matches
            for match in rep.matches[:5]:
                snippet = match.line_content
                if len(snippet) > 85:
                    snippet = snippet[:82] + "..."
                print(f"   L{match.line_number:<4} [{match.matched_word}]: {snippet}")
            if len(rep.matches) > 5:
                print(f"   ... and {len(rep.matches) - 5} more lines.")
            print()

    print("-" * 80)
    print(" SUMMARY TABLE")
    print("-" * 80)
    print(f"{'File Path':<60} | {'Count':<6} | {'Words'}")
    print("-" * 80)
    for rep in reports:
        try:
            rel_path = str(rep.file_path.relative_to(project_root))
        except ValueError:
            rel_path = str(rep.file_path)
        if len(rel_path) > 58:
            rel_path = "..." + rel_path[-55:]
        top_words = ", ".join(sorted(rep.unique_words)[:4])
        print(f"{rel_path:<60} | {rep.total_occurrences:<6} | {top_words}")
    print("-" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Detect French language drift (docstrings, comments, UI strings) in SimPulse codebase."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["simpulse", "scripts", "main_qt.py", "Makefile"],
        help="Paths to scan (default: simpulse, scripts, main_qt.py, Makefile)"
    )
    parser.add_argument(
        "-s", "--summary-only",
        action="store_true",
        help="Print summary only without detailed line snippets"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=[".py"],
        help="File extensions to scan (default: .py)"
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit with returncode 1 if any French drift is found (useful for CI)"
    )

    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent

    target_exts = set(args.ext)
    all_reports: List[FileDriftReport] = []

    for path_str in args.paths:
        target_path = Path(path_str)
        if not target_path.is_absolute():
            target_path = project_root / target_path

        if not target_path.exists():
            continue

        if target_path.is_file():
            if target_path.name in IGNORE_FILES:
                continue
            if target_path.suffix.lower() in target_exts:
                rep = scan_file(target_path)
                if rep.total_occurrences > 0:
                    all_reports.append(rep)
        elif target_path.is_dir():
            all_reports.extend(scan_directory(target_path, target_exts))

    # De-duplicate reports by file path
    seen_paths = set()
    unique_reports: List[FileDriftReport] = []
    for r in all_reports:
        if r.file_path not in seen_paths:
            seen_paths.add(r.file_path)
            unique_reports.append(r)

    if args.json:
        output_data = {
            "total_files": len(unique_reports),
            "total_occurrences": sum(r.total_occurrences for r in unique_reports),
            "files": [
                {
                    "file": str(r.file_path.relative_to(project_root) if r.file_path.is_relative_to(project_root) else r.file_path),
                    "occurrences": r.total_occurrences,
                    "unique_words": sorted(r.unique_words),
                    "matches": [
                        {
                            "line": m.line_number,
                            "word": m.matched_word,
                            "content": m.line_content,
                        }
                        for m in r.matches
                    ]
                }
                for r in unique_reports
            ]
        }
        print(json.dumps(output_data, indent=2, ensure_ascii=False))
    else:
        print_cli_report(unique_reports, project_root, verbose=not args.summary_only)

    if args.fail_on_drift and unique_reports:
        sys.exit(1)


if __name__ == "__main__":
    main()
