"""Tests for Guess That Song plugin — game lifecycle, scoring, UI blocks."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gilbert.interfaces.music import (
    AlbumInfo,
    ArtistInfo,
    PlaylistDetail,
    PlaylistInfo,
    SearchResults,
    TrackInfo,
)
from gilbert.interfaces.ui import ToolOutput, UIBlock

# ── Plugin imports ───────────────────────────────────────────────────
# The plugin uses relative imports, so we register it as a proper package.

_plugins_root = Path(__file__).resolve().parent.parent.parent / "plugins"
_plugin_dir = _plugins_root / "guess-that-song"

_pkg_name = "guess_that_song"
if _pkg_name not in sys.modules:
    pkg = ModuleType(_pkg_name)
    pkg.__path__ = [str(_plugin_dir)]
    pkg.__package__ = _pkg_name
    sys.modules[_pkg_name] = pkg

    for _mod_name in ("game", "scoring", "service"):
        _spec = importlib.util.spec_from_file_location(
            f"{_pkg_name}.{_mod_name}",
            _plugin_dir / f"{_mod_name}.py",
            submodule_search_locations=[],
        )
        _mod = importlib.util.module_from_spec(_spec)
        _mod.__package__ = _pkg_name
        sys.modules[f"{_pkg_name}.{_mod_name}"] = _mod
        _spec.loader.exec_module(_mod)
        setattr(pkg, _mod_name, _mod)

import guess_that_song.game as game_mod
import guess_that_song.scoring as scoring_mod
import guess_that_song.service as service_mod


# ── Fakes ────────────────────────────────────────────────────────────


def _make_track(
    track_id: str = "t1",
    name: str = "Never Gonna Give You Up",
    artist: str = "Rick Astley",
    duration: float = 213.0,
) -> TrackInfo:
    return TrackInfo(
        track_id=track_id,
        name=name,
        artists=[ArtistInfo(artist_id=f"a_{track_id}", name=artist)],
        album=AlbumInfo(
            album_id=f"al_{track_id}", name="Whenever You Need Somebody",
            album_art_url=f"https://img/{track_id}.jpg",
        ),
        duration_seconds=duration,
        uri=f"spotify:track:{track_id}",
    )


class FakeMusicService:
    def __init__(self, tracks: list[TrackInfo] | None = None) -> None:
        self._tracks = tracks or [
            _make_track("t1", "Never Gonna Give You Up", "Rick Astley"),
            _make_track("t2", "Take On Me", "a-ha"),
            _make_track("t3", "Don't Stop Believin'", "Journey"),
            _make_track("t4", "Bohemian Rhapsody", "Queen"),
            _make_track("t5", "Sweet Child O' Mine", "Guns N' Roses"),
        ]
        self.play_calls: list[dict[str, Any]] = []

    def service_info(self) -> Any:
        from gilbert.interfaces.service import ServiceInfo
        return ServiceInfo(name="music", capabilities=frozenset({"music"}))

    async def search(self, query: str, *, limit: int = 10) -> SearchResults:
        return SearchResults(tracks=self._tracks[:limit])

    async def get_playlist(self, playlist_id: str) -> PlaylistDetail | None:
        return None

    async def play_track(
        self,
        track_id: str,
        speaker_names: list[str] | None = None,
        volume: int | None = None,
        position_seconds: float | None = None,
    ) -> TrackInfo:
        self.play_calls.append({
            "track_id": track_id,
            "speaker_names": speaker_names,
            "volume": volume,
            "position_seconds": position_seconds,
        })
        for t in self._tracks:
            if t.track_id == track_id:
                return t
        raise KeyError(f"Track not found: {track_id}")


class FakeSpeakerService:
    def __init__(self) -> None:
        self.backend = AsyncMock()
        self.backend.list_speakers = AsyncMock(return_value=[])
        self.backend.stop = AsyncMock()
        self.announce_calls: list[str] = []

    def service_info(self) -> Any:
        from gilbert.interfaces.service import ServiceInfo
        return ServiceInfo(name="speaker", capabilities=frozenset({"speaker_control"}))

    async def resolve_speaker_names(self, names: list[str]) -> list[str]:
        return [f"id_{n}" for n in names]

    async def announce(
        self, text: str, speaker_names: list[str] | None = None,
        volume: int | None = None, voice_name: str | None = None,
    ) -> str:
        self.announce_calls.append(text)
        return "/tmp/fake.mp3"


class FakeResolver:
    def __init__(
        self,
        music: FakeMusicService | None = None,
        speaker: FakeSpeakerService | None = None,
        ai: Any = None,
    ) -> None:
        self._caps: dict[str, Any] = {
            "music": music or FakeMusicService(),
            "speaker_control": speaker or FakeSpeakerService(),
        }
        if ai is not None:
            self._caps["ai_chat"] = ai

    def get_capability(self, cap: str) -> Any:
        return self._caps.get(cap)

    def require_capability(self, cap: str) -> Any:
        svc = self._caps.get(cap)
        if svc is None:
            raise LookupError(f"Missing capability: {cap}")
        return svc

    def get_all(self, cap: str) -> list[Any]:
        svc = self._caps.get(cap)
        return [svc] if svc else []


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def music_svc() -> FakeMusicService:
    return FakeMusicService()


@pytest.fixture
def speaker_svc() -> FakeSpeakerService:
    return FakeSpeakerService()


@pytest.fixture
async def service(music_svc: FakeMusicService, speaker_svc: FakeSpeakerService):
    svc = service_mod.GuessGameService(config={
        "default_clip_seconds": 3,
        "default_num_rounds": 5,
        "default_volume": 70,
        "max_rounds": 20,
        "max_concurrent_games": 3,
    })
    resolver = FakeResolver(music=music_svc, speaker=speaker_svc)
    await svc.start(resolver)
    return svc


# ── Tool definition tests ───────────────────────────────────────────


class TestToolDefinitions:
    async def test_get_tools_returns_all_tools(self, service: service_mod.GuessGameService) -> None:
        tools = service.get_tools()
        names = {t.name for t in tools}
        assert names == {
            "guess_song_setup", "guess_song_create", "guess_song_join",
            "guess_song_start", "guess_song_submit_guess",
            "guess_song_action", "guess_song_status",
        }

    async def test_tool_provider_name(self, service: service_mod.GuessGameService) -> None:
        assert service.tool_provider_name == "guess_game"

    async def test_service_info(self, service: service_mod.GuessGameService) -> None:
        info = service.service_info()
        assert info.name == "guess_game"
        assert "ai_tools" in info.capabilities
        assert "guess_game" in info.capabilities
        assert "music" in info.requires
        assert "speaker_control" in info.requires


# ── Setup form tests ─────────────────────────────────────────────────


class TestSetupForm:
    async def test_setup_returns_tool_output_with_form(self, service: service_mod.GuessGameService) -> None:
        result = await service.execute_tool("guess_song_setup", {})
        assert isinstance(result, ToolOutput)
        assert len(result.ui_blocks) == 1
        block = result.ui_blocks[0]
        assert block.block_type == "form"
        assert "Guess That Song" in block.title

        # Check form has expected elements
        names = {e.name for e in block.elements}
        assert "query" in names
        assert "num_rounds" in names
        assert "clip_seconds" in names
        assert "volume" in names


# ── Game lifecycle tests ─────────────────────────────────────────────


class TestGameLifecycle:
    async def _create_game(self, service: service_mod.GuessGameService, **kwargs: Any) -> str:
        """Helper to create a game and return the game_id."""
        args = {
            "query": "80s rock",
            "num_rounds": 3,
            "clip_seconds": 3,
            "volume": 70,
            "_user_id": "host1",
            "_user_name": "Alice",
            **kwargs,
        }
        result = await service.execute_tool("guess_song_create", args)
        assert isinstance(result, ToolOutput)
        assert "created" in result.text.lower() or "game" in result.text.lower()
        # Extract game_id from the service's internal state
        games = list(service._games.values())
        assert len(games) >= 1
        return games[-1].game_id

    async def test_create_game(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        game = service._games[game_id]
        assert game.status == "lobby"
        assert game.host_id == "host1"
        assert game.config.query == "80s rock"
        assert game.config.num_rounds == 3
        assert "host1" in game.players

    async def test_create_returns_lobby_ui(self, service: service_mod.GuessGameService) -> None:
        result = await service.execute_tool("guess_song_create", {
            "query": "jazz", "_user_id": "h", "_user_name": "H",
        })
        assert isinstance(result, ToolOutput)
        assert len(result.ui_blocks) == 1
        block = result.ui_blocks[0]
        # Should have a start button
        button_els = [e for e in block.elements if e.type == "buttons"]
        assert len(button_els) == 1
        assert any(o.value == "start" for o in button_els[0].options)

    async def test_join_game(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_join", {
            "game_id": game_id, "_user_id": "p2", "_user_name": "Bob",
        })
        assert isinstance(result, str)
        assert "joined" in result.lower()
        game = service._games[game_id]
        assert "p2" in game.players
        assert len(game.players) == 2

    async def test_join_nonexistent_game(self, service: service_mod.GuessGameService) -> None:
        result = await service.execute_tool("guess_song_join", {
            "game_id": "nope", "_user_id": "p1", "_user_name": "X",
        })
        assert "no game" in result.lower()

    async def test_join_already_joined(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_join", {
            "game_id": game_id, "_user_id": "host1", "_user_name": "Alice",
        })
        assert "already" in result.lower()

    async def test_start_game_plays_clip(
        self, service: service_mod.GuessGameService, music_svc: FakeMusicService,
    ) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "host1",
        })
        assert isinstance(result, ToolOutput)
        assert "round 1" in result.text.lower()
        # Check that music was played
        assert len(music_svc.play_calls) == 1
        call = music_svc.play_calls[0]
        assert call["position_seconds"] is not None
        assert call["position_seconds"] >= 10.0

        game = service._games[game_id]
        assert game.status == "playing"
        assert game.current_round == 1

    async def test_start_returns_guess_form(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "host1",
        })
        assert isinstance(result, ToolOutput)
        assert len(result.ui_blocks) == 1
        block = result.ui_blocks[0]
        guess_inputs = [e for e in block.elements if e.name == "guess"]
        assert len(guess_inputs) == 1
        assert guess_inputs[0].type == "text"

    async def test_non_host_cannot_start(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        await service.execute_tool("guess_song_join", {
            "game_id": game_id, "_user_id": "p2", "_user_name": "Bob",
        })
        result = await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "p2",
        })
        assert isinstance(result, str)
        assert "host" in result.lower()

    async def test_submit_guess_and_auto_reveal(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service, num_rounds=1)
        await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "host1",
        })
        # Single player → submitting guess auto-reveals
        result = await service.execute_tool("guess_song_submit_guess", {
            "game_id": game_id, "guess": "Never Gonna Give You Up",
            "_user_id": "host1", "_user_name": "Alice",
        })
        # Should be a ToolOutput with reveal info and action buttons
        assert isinstance(result, ToolOutput)
        assert "by" in result.text.lower()  # "Song by Artist"

    async def test_multiplayer_guess_flow(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service, num_rounds=1)
        await service.execute_tool("guess_song_join", {
            "game_id": game_id, "_user_id": "p2", "_user_name": "Bob",
        })
        await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "host1",
        })
        # First guess — should wait
        result1 = await service.execute_tool("guess_song_submit_guess", {
            "game_id": game_id, "guess": "some guess",
            "_user_id": "host1", "_user_name": "Alice",
        })
        assert isinstance(result1, str)
        assert "waiting" in result1.lower()

        # Second guess — should trigger reveal
        result2 = await service.execute_tool("guess_song_submit_guess", {
            "game_id": game_id, "guess": "another guess",
            "_user_id": "p2", "_user_name": "Bob",
        })
        assert isinstance(result2, ToolOutput)

    async def test_duplicate_guess_rejected(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service, num_rounds=2)
        await service.execute_tool("guess_song_join", {
            "game_id": game_id, "_user_id": "p2", "_user_name": "Bob",
        })
        await service.execute_tool("guess_song_start", {
            "game_id": game_id, "_user_id": "host1",
        })
        await service.execute_tool("guess_song_submit_guess", {
            "game_id": game_id, "guess": "first",
            "_user_id": "host1", "_user_name": "Alice",
        })
        result = await service.execute_tool("guess_song_submit_guess", {
            "game_id": game_id, "guess": "second try",
            "_user_id": "host1", "_user_name": "Alice",
        })
        assert isinstance(result, str)
        assert "already" in result.lower()

    async def test_end_game(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_action", {
            "game_id": game_id, "action": "end",
        })
        assert isinstance(result, ToolOutput)
        assert "game over" in result.text.lower()
        assert game_id not in service._games

    async def test_status_no_games(self, service: service_mod.GuessGameService) -> None:
        result = await service.execute_tool("guess_song_status", {})
        assert "no active" in result.lower()

    async def test_status_with_game(self, service: service_mod.GuessGameService) -> None:
        game_id = await self._create_game(service)
        result = await service.execute_tool("guess_song_status", {"game_id": game_id})
        assert isinstance(result, str)
        assert game_id in result
        assert "lobby" in result.lower()

    async def test_max_concurrent_games(self, service: service_mod.GuessGameService) -> None:
        for i in range(3):
            await self._create_game(service, _user_id=f"host{i}", _user_name=f"H{i}")
        result = await service.execute_tool("guess_song_create", {
            "query": "test", "_user_id": "host99", "_user_name": "Overflow",
        })
        assert isinstance(result, ToolOutput)
        assert "too many" in result.text.lower()


# ── Scoring tests ────────────────────────────────────────────────────


class TestScoring:
    def test_exact_title_match(self) -> None:
        result = scoring_mod.check_guess_exact(
            "Never Gonna Give You Up", "Never Gonna Give You Up", "Rick Astley",
        )
        assert result["title"] is True

    def test_substring_title_match(self) -> None:
        result = scoring_mod.check_guess_exact(
            "never gonna give you up by rick astley",
            "Never Gonna Give You Up", "Rick Astley",
        )
        assert result["title"] is True
        assert result["artist"] is True

    def test_title_in_guess(self) -> None:
        result = scoring_mod.check_guess_exact(
            "I think it's take on me", "Take On Me", "a-ha",
        )
        assert result["title"] is True

    def test_no_match(self) -> None:
        result = scoring_mod.check_guess_exact(
            "Stairway to Heaven", "Never Gonna Give You Up", "Rick Astley",
        )
        assert result["title"] is False
        assert result["artist"] is False

    def test_short_guess_rejected(self) -> None:
        result = scoring_mod.check_guess_exact("hi", "Hi", "Artist")
        assert result["title"] is False

    async def test_score_round_correct_guess(self) -> None:
        song = game_mod.SongInfo(
            track_id="t1", title="Take On Me", artist="a-ha",
            uri="x", duration_seconds=200,
        )
        guesses = [
            game_mod.PlayerGuess(
                player_id="p1", player_name="Alice",
                guess_text="Take On Me", timestamp=1.0,
            ),
        ]
        results = await scoring_mod.score_round(guesses, song)
        assert len(results) == 1
        assert results[0]["got_title"] is True
        assert results[0]["is_fastest"] is True
        assert results[0]["points"] >= 1

    async def test_score_round_speed_bonus(self) -> None:
        song = game_mod.SongInfo(
            track_id="t1", title="Take On Me", artist="a-ha",
            uri="x", duration_seconds=200,
        )
        guesses = [
            game_mod.PlayerGuess(
                player_id="p1", player_name="Alice",
                guess_text="Take On Me", timestamp=1.0,
            ),
            game_mod.PlayerGuess(
                player_id="p2", player_name="Bob",
                guess_text="take on me by a-ha", timestamp=2.0,
            ),
        ]
        results = await scoring_mod.score_round(guesses, song)
        # Alice should get fastest bonus, Bob should not
        alice = next(r for r in results if r["player_id"] == "p1")
        bob = next(r for r in results if r["player_id"] == "p2")
        assert alice["is_fastest"] is True
        assert bob["is_fastest"] is False


# ── Game state tests ─────────────────────────────────────────────────


class TestGameState:
    def test_add_and_remove_player(self) -> None:
        game = game_mod.GameState()
        game.add_player("p1", "Alice")
        assert "p1" in game.players
        assert game.scores["p1"] == 0

        game.remove_player("p1")
        assert "p1" not in game.players
        assert "p1" not in game.scores

    def test_all_guessed(self) -> None:
        game = game_mod.GameState()
        game.add_player("p1", "Alice")
        game.add_player("p2", "Bob")
        assert game.all_guessed() is False

        game.guesses["p1"] = game_mod.PlayerGuess(
            player_id="p1", player_name="Alice", guess_text="test",
        )
        assert game.all_guessed() is False

        game.guesses["p2"] = game_mod.PlayerGuess(
            player_id="p2", player_name="Bob", guess_text="test2",
        )
        assert game.all_guessed() is True

    def test_format_scores(self) -> None:
        game = game_mod.GameState()
        game.add_player("p1", "Alice")
        game.add_player("p2", "Bob")
        game.scores["p1"] = 5
        game.scores["p2"] = 3
        text = game.format_scores()
        assert "Alice" in text
        assert "Bob" in text
        # Alice should be first (higher score)
        assert text.index("Alice") < text.index("Bob")

    def test_format_final_scores_with_winner(self) -> None:
        game = game_mod.GameState()
        game.add_player("p1", "Alice")
        game.add_player("p2", "Bob")
        game.scores["p1"] = 5
        game.scores["p2"] = 3
        text = game.format_final_scores()
        assert "Alice wins" in text
        assert "Game Over" in text

    def test_format_final_scores_tie(self) -> None:
        game = game_mod.GameState()
        game.add_player("p1", "Alice")
        game.add_player("p2", "Bob")
        game.scores["p1"] = 4
        game.scores["p2"] = 4
        text = game.format_final_scores()
        assert "tie" in text.lower()

    def test_current_song(self) -> None:
        game = game_mod.GameState()
        song = game_mod.SongInfo(
            track_id="t1", title="Test", artist="A", uri="x", duration_seconds=100,
        )
        game.songs = [song]
        game.current_round = 1
        assert game.current_song == song
        game.current_round = 0
        assert game.current_song is None

    def test_rounds_remaining(self) -> None:
        game = game_mod.GameState(config=game_mod.GameConfig(num_rounds=5))
        game.current_round = 2
        assert game.rounds_remaining == 3
