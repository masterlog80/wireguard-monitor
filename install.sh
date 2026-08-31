#!/usr/bin/env bash
# =============================================================================
# install.sh - Clone (with GitHub token auth + pending PR selection) and set
# up wireguard-monitor for local use.
# =============================================================================
# This script is meant to be fetched and run via:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/masterlog80/wireguard-monitor/main/install.sh)"
#
# Optional environment variables:
#   GH_TOKEN / GITHUB_TOKEN   GitHub token used to authenticate the clone and
#                             to list open pull requests. Prompted for if
#                             unset. This repo is currently private, so a
#                             token is required for the clone itself to
#                             succeed -- leaving it blank will only work once
#                             (if ever) the repo is made public.
#   REPO                      GitHub repo to clone. Default: masterlog80/wireguard-monitor
#   DIRNAME                   Target directory. Default: wireguard-monitor
#                             (use DIRNAME=/opt/wireguard-monitor, run as
#                             root, for the systemd-service layout described
#                             in the README).
#
# What it does NOT do: it does not create the systemd service, the
# /var/lib/wireguard-monitor data directory, or /etc/wireguard-monitor.env --
# those set real credentials and touch the host outside this directory, so
# they stay as explicit, reviewable steps in the README's "Running as a
# systemd Service" section rather than being silently automated here.
# =============================================================================

set -e

REPO="${REPO:-masterlog80/wireguard-monitor}"
DIRNAME="${DIRNAME:-wireguard-monitor}"

echo ""
echo ">> Step 1/4: GitHub authentication"
GH_TOKEN="${GH_TOKEN:-$GITHUB_TOKEN}"
if [[ -n "$GH_TOKEN" ]]; then
  echo "   Using existing GH_TOKEN/GITHUB_TOKEN from the environment."
else
  read -s -p "   GitHub token (required -- this repo is private): " GH_TOKEN
  echo
fi

AUTH_HEADER=()
[[ -n "$GH_TOKEN" ]] && AUTH_HEADER=(-H "Authorization: token ${GH_TOKEN}")
if [[ -z "$GH_TOKEN" ]]; then
  echo "   Warning: no token provided. This repo is currently private, so the"
  echo "   clone below will fail unless you have some other auth configured"
  echo "   (e.g. an SSH key + a 'git config --global url.\"git@github.com:\"."
  echo "   insteadOf \"https://github.com/\"' rewrite, or a credential helper)."
fi

echo ""
echo ">> Step 2/4: Checking for open pending pull requests"
CLONE_REF=""
if command -v jq &>/dev/null; then
  PR_JSON=$(curl -s "${AUTH_HEADER[@]}" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO}/pulls?state=open")

  CANDIDATES=()
  while IFS=$'\t' read -r pr_number pr_branch pr_title; do
    [[ -z "$pr_number" ]] && continue
    CANDIDATES+=("${pr_number}"$'\t'"${pr_branch}"$'\t'"${pr_title}")
  done < <(echo "$PR_JSON" | jq -r '.[] | select(.draft == false) | [.number, .head.ref, .title] | @tsv')

  if [[ ${#CANDIDATES[@]} -gt 0 ]]; then
    echo "   Open pending PR(s) found (not yet merged to main):"
    for i in "${!CANDIDATES[@]}"; do
      IFS=$'\t' read -r num branch title <<< "${CANDIDATES[$i]}"
      echo "     $((i+1))) #${num} ${title} (branch: ${branch})"
    done
    echo "     0) none - use main"
    read -p "   Which one should be cloned? [0-${#CANDIDATES[@]}, default 0]: " choice
    choice="${choice:-0}"
    if [[ "$choice" =~ ^[1-9][0-9]*$ ]] && (( choice <= ${#CANDIDATES[@]} )); then
      IFS=$'\t' read -r _ CLONE_REF _ <<< "${CANDIDATES[$((choice-1))]}"
    fi
  else
    echo "   No open pending PRs - will use main."
  fi
else
  echo "   jq not found - skipping pending PR check, will use main."
fi

echo ""
echo ">> Step 3/4: Cloning repository"
CLONE_ARGS=()
[[ -n "$CLONE_REF" ]] && CLONE_ARGS=(-b "$CLONE_REF")
echo "   Ref: ${CLONE_REF:-main (default branch)}"
echo "   Target: ${DIRNAME}"

if [[ -d "$DIRNAME" ]]; then
  echo "   '${DIRNAME}' already exists -- skipping clone. Remove it first for a fresh clone."
elif [[ -n "$GH_TOKEN" ]]; then
  # Auth header is passed via git config, not embedded in the URL, so it's
  # never written to .git/config or left lying around on disk.
  git -c http.extraHeader="Authorization: Basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)" \
    clone "${CLONE_ARGS[@]}" "https://github.com/${REPO}.git" "$DIRNAME"
else
  git clone "${CLONE_ARGS[@]}" "https://github.com/${REPO}.git" "$DIRNAME"
fi
cd "${DIRNAME}"

echo ""
echo ">> Step 4/4: Setting up a Python virtual environment"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo ""
echo "Completed. From '${DIRNAME}':"
echo "  - Local/dev use: export ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY,"
echo "    then run 'venv/bin/python run.py'. See the README's Quick Start"
echo "    section for the exact commands."
echo "  - systemd service: continue with the README's 'Running as a"
echo "    systemd Service' section from step 2 onward (this script's clone"
echo "    covers step 1 -- re-run it with DIRNAME=/opt/wireguard-monitor as"
echo "    root/sudo if you haven't cloned there yet)."
