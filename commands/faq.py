# ENTIRELY LLM GENERATED, NO HUMAN EVEN LOOKED AT THIS CODE

import asyncio
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from time import time
from typing import List, Tuple
from urllib.request import urlopen

import discord
from discord import app_commands
from discord.ext.commands import Cog


FAQ_PAGE_URL = "https://github.com/nekename/OpenDeck/wiki/0.-FAQ"
FAQ_MARKDOWN_URL = "https://raw.githubusercontent.com/wiki/nekename/OpenDeck/0.-FAQ.md"


@dataclass
class FaqEntry:
    section: str
    question: str
    answer: str


class Faq(Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cache: List[FaqEntry] = []
        self._cache_expiry = 0.0
        self._cache_ttl_seconds = 900
        self._auto_reply_min_score = 95

        self._faq_reply_context_menu = app_commands.ContextMenu(
            name = "Reply With FAQ Match",
            callback = self.reply_with_faq_match
        )

        existing = self.bot.tree.get_command(
            self._faq_reply_context_menu.name,
            type = discord.AppCommandType.message
        )
        if existing is None:
            self.bot.tree.add_command(self._faq_reply_context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self._faq_reply_context_menu.name,
            type = discord.AppCommandType.message
        )

    @app_commands.command(description = "Searches the OpenDeck FAQ for your question")
    @app_commands.describe(query = "Type any OpenDeck question or keywords")
    async def faq(self, ctx: discord.Interaction, query: str):
        await ctx.response.defer(thinking = True)
        embed, _ = await self._build_faq_search_embed(query)
        await ctx.followup.send(embed = embed)

    async def reply_with_faq_match(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral = True, thinking = True)

        query = (message.content or "").strip()
        if not query:
            await interaction.followup.send(
                "That message has no text content for FAQ matching.",
                ephemeral = True
            )
            return

        embed, matched = await self._build_faq_search_embed(query)
        if not matched:
            await interaction.followup.send(embed = embed, ephemeral = True)
            return

        try:
            await message.reply(embed = embed)
            await interaction.followup.send(
                "Posted an FAQ reply to that message.",
                ephemeral = True
            )
        except Exception:
            await interaction.followup.send(
                "I found a match but could not post the reply in that channel.",
                ephemeral = True
            )

    async def _build_faq_search_embed(self, query: str) -> Tuple[discord.Embed, bool]:
        try:
            entries = await self._get_faq_entries()
        except Exception:
            embed = discord.Embed(
                color = discord.Colour.red(),
                title = "OpenDeck FAQ unavailable",
                description = "I could not fetch the FAQ right now. Please try again in a moment."
            )
            embed.add_field(name = "Source", value = FAQ_PAGE_URL, inline = False)
            return embed, False

        if not entries:
            embed = discord.Embed(
                color = discord.Colour.red(),
                title = "No FAQ data found",
                description = "I fetched the FAQ page but could not parse any questions."
            )
            embed.add_field(name = "Source", value = FAQ_PAGE_URL, inline = False)
            return embed, False

        scored = sorted(
            ((self._score_entry(query, entry), entry) for entry in entries),
            key = lambda item: item[0],
            reverse = True
        )
        best_score, best_entry = scored[0]

        if best_score < 35:
            suggestions = [entry.question for score, entry in scored[:3] if score > 0]
            embed = discord.Embed(
                color = discord.Colour.orange(),
                title = "I could not find a close FAQ match",
                description = "Try rephrasing your question with more specific terms."
            )

            if suggestions:
                embed.add_field(name = "Closest matches", value = "\n".join(f"- {item}" for item in suggestions), inline = False)

            embed.add_field(name = "OpenDeck FAQ", value = FAQ_PAGE_URL, inline = False)
            return embed, False

        answer = self._trim_answer(best_entry.answer)
        embed = discord.Embed(
            color = discord.Colour.blurple(),
            title = best_entry.question[:256],
            description = answer
        )
        embed.add_field(name = "Section", value = best_entry.section, inline = True)
        embed.add_field(name = "Source", value = FAQ_PAGE_URL, inline = True)
        embed.set_footer(text = "Result from OpenDeck FAQ")
        return embed, True

    async def _get_faq_entries(self) -> List[FaqEntry]:
        now = time()
        if self._cache and now < self._cache_expiry:
            return self._cache

        markdown = await asyncio.to_thread(self._download_faq_markdown)
        entries = self._parse_faq_entries(markdown)

        self._cache = entries
        self._cache_expiry = now + self._cache_ttl_seconds
        return entries

    def _download_faq_markdown(self) -> str:
        with urlopen(FAQ_MARKDOWN_URL, timeout = 15) as response:
            return response.read().decode("utf-8", errors = "replace")

    def _parse_faq_entries(self, markdown: str) -> List[FaqEntry]:
        entries: List[FaqEntry] = []
        section = "General"
        question = ""
        answer_lines: List[str] = []

        def flush_entry() -> None:
            if not question:
                return
            answer = "\n".join(answer_lines).strip()
            if not answer:
                return
            entries.append(FaqEntry(section = section, question = question, answer = answer))

        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()

            if line.startswith("## "):
                flush_entry()
                section = line[3:].strip()
                question = ""
                answer_lines = []
                continue

            if line.startswith("### "):
                flush_entry()
                question = line[4:].strip()
                answer_lines = []
                continue

            if not question:
                continue

            if line.strip() == "---":
                continue

            answer_lines.append(line)

        flush_entry()
        return entries

    def _score_entry(self, query: str, entry: FaqEntry) -> int:
        normalized_query = self._normalize(query)
        if not normalized_query:
            return 0

        normalized_question = self._normalize(entry.question)
        normalized_answer = self._normalize(entry.answer[:1200])
        corpus = f"{normalized_question} {normalized_answer}"

        score = 0
        if normalized_query in normalized_question:
            score += 140
        elif normalized_query in corpus:
            score += 90

        tokens = [token for token in normalized_query.split() if len(token) >= 3]
        if not tokens:
            tokens = normalized_query.split()

        for token in tokens:
            if token in normalized_question:
                score += 20
            elif token in corpus:
                score += 8

        similarity = SequenceMatcher(None, normalized_query, normalized_question).ratio()
        score += int(similarity * 60)
        return score

    def _normalize(self, value: str) -> str:
        lowered = value.lower()
        cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _trim_answer(self, answer: str, max_chars: int = 1800) -> str:
        cleaned = answer.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return f"{cleaned[:max_chars - 3].rstrip()}..."
