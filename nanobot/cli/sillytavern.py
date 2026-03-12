"""CLI commands for SillyTavern content management."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

st_app = typer.Typer(help="Manage SillyTavern content (characters, world info, presets)")
console = Console()


# ============================================================================
# Character Commands
# ============================================================================

char_app = typer.Typer(help="Manage character cards")
st_app.add_typer(char_app, name="char")


@char_app.command("import")
def char_import(
    file: str = typer.Argument(..., help="Path to character card JSON file"),
):
    """Import a SillyTavern character card."""
    from nanobot.sillytavern.character_card import parse_character_card, to_stored_character_card
    from nanobot.sillytavern.storage import import_character

    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    content = path.read_text("utf-8")
    data, error, spec = parse_character_card(content)
    if error:
        console.print(f"[red]Parse error: {error}[/red]")
        raise typer.Exit(1)

    stored = to_stored_character_card(data, spec, str(path.resolve()))
    import_character(stored)
    console.print(f"[green]✓[/green] Imported character: {stored.name} ({spec})")


@char_app.command("list")
def char_list():
    """List imported character cards."""
    from nanobot.sillytavern.storage import list_characters, get_active_character

    chars = list_characters()
    if not chars:
        console.print("[dim]No characters imported.[/dim]")
        return

    active = get_active_character()
    active_id = active.id if active else ""

    table = Table(title="Character Cards")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Status", style="green")

    for c in chars:
        status = "★ active" if c.get("id") == active_id else ""
        table.add_row(c.get("name", ""), c.get("id", "")[:20] + "...", status)

    console.print(table)


@char_app.command("show")
def char_show(name: str = typer.Argument(..., help="Character name")):
    """Show character card details."""
    from nanobot.sillytavern.storage import get_character_by_name
    from nanobot.sillytavern.character_card import build_character_prompt

    card = get_character_by_name(name)
    if not card:
        console.print(f"[red]Character not found: {name}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]{card.name}[/bold cyan] ({card.spec})")
    console.print(f"ID: {card.id}")
    console.print(f"Source: {card.source_path}")
    console.print()

    prompt = build_character_prompt(card.data)
    console.print(prompt)


@char_app.command("activate")
def char_activate(name: str = typer.Argument(..., help="Character name")):
    """Set a character as active."""
    from nanobot.sillytavern.storage import get_character_by_name, activate_character

    card = get_character_by_name(name)
    if not card:
        console.print(f"[red]Character not found: {name}[/red]")
        raise typer.Exit(1)

    activate_character(card.id)
    console.print(f"[green]✓[/green] Activated: {card.name}")


@char_app.command("deactivate")
def char_deactivate():
    """Clear active character."""
    from nanobot.sillytavern.storage import deactivate_character
    deactivate_character()
    console.print("[green]✓[/green] Character deactivated")


@char_app.command("delete")
def char_delete(name: str = typer.Argument(..., help="Character name")):
    """Delete a character card."""
    from nanobot.sillytavern.storage import get_character_by_name, delete_character

    card = get_character_by_name(name)
    if not card:
        console.print(f"[red]Character not found: {name}[/red]")
        raise typer.Exit(1)

    if typer.confirm(f"Delete '{card.name}'?"):
        delete_character(card.id)
        console.print(f"[green]✓[/green] Deleted: {card.name}")


# ============================================================================
# World Info Commands
# ============================================================================

wi_app = typer.Typer(help="Manage world info (lorebooks)")
st_app.add_typer(wi_app, name="wi")


@wi_app.command("import")
def wi_import(
    file: str = typer.Argument(..., help="Path to world info JSON file"),
    name: str = typer.Option(None, "--name", "-n", help="Book name (default: filename)"),
):
    """Import a world info book."""
    from nanobot.sillytavern.world_info import parse_world_info, summarize_world_info
    from nanobot.sillytavern.storage import import_world_info
    from nanobot.sillytavern.types import StoredWorldInfoBook
    from nanobot.sillytavern.character_card import generate_character_id
    from datetime import datetime

    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    content = path.read_text("utf-8")
    book, error = parse_world_info(content)
    if error:
        console.print(f"[red]Parse error: {error}[/red]")
        raise typer.Exit(1)

    book_name = name or path.stem
    stored = StoredWorldInfoBook(
        id=generate_character_id(book_name),
        name=book_name,
        imported_at=datetime.now().isoformat(),
        source_path=str(path.resolve()),
        enabled=True,
        entries=book.entries,
    )
    import_world_info(stored)
    summary = summarize_world_info(book)
    console.print(f"[green]✓[/green] Imported world info: {book_name} — {summary}")


@wi_app.command("list")
def wi_list():
    """List imported world info books."""
    from nanobot.sillytavern.storage import list_world_info

    books = list_world_info()
    if not books:
        console.print("[dim]No world info imported.[/dim]")
        return

    table = Table(title="World Info Books")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Entries")
    table.add_column("Status", style="green")

    for b in books:
        status = "enabled" if b.get("enabled", True) else "[dim]disabled[/dim]"
        table.add_row(
            b.get("name", ""),
            b.get("id", "")[:20] + "...",
            str(b.get("entry_count", "?")),
            status,
        )

    console.print(table)


@wi_app.command("enable")
def wi_enable(name: str = typer.Argument(..., help="Book name or ID")):
    """Enable a world info book."""
    _wi_toggle(name, True)


@wi_app.command("disable")
def wi_disable(name: str = typer.Argument(..., help="Book name or ID")):
    """Disable a world info book."""
    _wi_toggle(name, False)


def _wi_toggle(name: str, enabled: bool):
    from nanobot.sillytavern.storage import list_world_info, set_world_info_enabled

    for b in list_world_info():
        if b.get("name", "").lower() == name.lower() or b.get("id", "") == name:
            set_world_info_enabled(b["id"], enabled)
            action = "Enabled" if enabled else "Disabled"
            console.print(f"[green]✓[/green] {action}: {b.get('name')}")
            return
    console.print(f"[red]World info not found: {name}[/red]")


@wi_app.command("delete")
def wi_delete(name: str = typer.Argument(..., help="Book name or ID")):
    """Delete a world info book."""
    from nanobot.sillytavern.storage import list_world_info, delete_world_info

    for b in list_world_info():
        if b.get("name", "").lower() == name.lower() or b.get("id", "") == name:
            if typer.confirm(f"Delete '{b.get('name')}'?"):
                delete_world_info(b["id"])
                console.print(f"[green]✓[/green] Deleted: {b.get('name')}")
            return
    console.print(f"[red]World info not found: {name}[/red]")


# ============================================================================
# Preset Commands
# ============================================================================

preset_app = typer.Typer(help="Manage presets")
st_app.add_typer(preset_app, name="preset")


@preset_app.command("import")
def preset_import(
    file: str = typer.Argument(..., help="Path to preset JSON file"),
    name: str = typer.Option(None, "--name", "-n", help="Preset name (default: filename)"),
):
    """Import a SillyTavern preset."""
    from nanobot.sillytavern.preset import parse_preset, summarize_preset
    from nanobot.sillytavern.storage import import_preset
    from nanobot.sillytavern.types import StoredPreset
    from nanobot.sillytavern.character_card import generate_character_id
    from datetime import datetime

    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    content = path.read_text("utf-8")
    preset, error = parse_preset(content)
    if error:
        console.print(f"[red]Parse error: {error}[/red]")
        raise typer.Exit(1)

    preset_name = name or path.stem
    stored = StoredPreset(
        id=generate_character_id(preset_name),
        name=preset_name,
        imported_at=datetime.now().isoformat(),
        source_path=str(path.resolve()),
        data=preset,
    )
    import_preset(stored)
    summary = summarize_preset(preset)
    console.print(f"[green]✓[/green] Imported preset: {preset_name} — {summary}")


@preset_app.command("list")
def preset_list():
    """List imported presets."""
    from nanobot.sillytavern.storage import list_presets, get_active_preset

    presets = list_presets()
    if not presets:
        console.print("[dim]No presets imported.[/dim]")
        return

    active = get_active_preset()
    active_id = active.id if active else ""

    table = Table(title="Presets")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Status", style="green")

    for p in presets:
        status = "★ active" if p.get("id") == active_id else ""
        table.add_row(p.get("name", ""), p.get("id", "")[:20] + "...", status)

    console.print(table)


@preset_app.command("activate")
def preset_activate(name: str = typer.Argument(..., help="Preset name")):
    """Set a preset as active."""
    from nanobot.sillytavern.storage import list_presets, activate_preset

    for p in list_presets():
        if p.get("name", "").lower() == name.lower():
            activate_preset(p["id"])
            console.print(f"[green]✓[/green] Activated: {p.get('name')}")
            return
    console.print(f"[red]Preset not found: {name}[/red]")


@preset_app.command("deactivate")
def preset_deactivate():
    """Clear active preset."""
    from nanobot.sillytavern.storage import deactivate_preset
    deactivate_preset()
    console.print("[green]✓[/green] Preset deactivated")


@preset_app.command("show")
def preset_show(name: str = typer.Argument(..., help="Preset name")):
    """Show preset details and prompt entries."""
    from nanobot.sillytavern.storage import list_presets, get_preset

    for p in list_presets():
        if p.get("name", "").lower() == name.lower():
            preset = get_preset(p["id"])
            if not preset:
                console.print(f"[red]Failed to load preset: {name}[/red]")
                return

            console.print(f"[bold]Preset: {preset.name}[/bold]\n")
            console.print(f"Temperature: {preset.data.temperature}")
            console.print(f"Top P: {preset.data.top_p}")
            console.print(f"Top K: {preset.data.top_k}")
            console.print(f"Frequency Penalty: {preset.data.frequency_penalty}")
            console.print(f"Presence Penalty: {preset.data.presence_penalty}")
            console.print(f"\n[bold]Prompt Entries:[/bold]\n")

            table = Table()
            table.add_column("#", style="dim", width=4)
            table.add_column("Name")
            table.add_column("Role", width=10)
            table.add_column("Enabled", width=8)
            table.add_column("Position", width=8)
            table.add_column("Content Preview", max_width=40)

            for idx, prompt in enumerate(preset.data.prompts):
                enabled_str = "[green]✓[/green]" if prompt.enabled else "[dim]✗[/dim]"
                preview = prompt.content[:40] + "..." if len(prompt.content) > 40 else prompt.content
                preview = preview.replace("\n", " ")
                table.add_row(
                    str(idx),
                    prompt.name or prompt.identifier,
                    prompt.role,
                    enabled_str,
                    str(prompt.injection_position),
                    preview
                )

            console.print(table)
            console.print(f"\n[dim]Tip: Use 'nanobot st preset toggle-prompt {name} <index>' to enable/disable prompts[/dim]")
            return
    console.print(f"[red]Preset not found: {name}[/red]")


@preset_app.command("toggle-prompt")
def preset_toggle_prompt(
    preset_name: str = typer.Argument(..., help="Preset name"),
    prompt_indices: str = typer.Argument(..., help="Prompt index or indices (e.g., '3' or '3,4,5,6' or '3-6')"),
):
    """Toggle one or more prompt entries in a preset."""
    from nanobot.sillytavern.storage import list_presets, get_preset, _preset_dir, _write_json
    from dataclasses import asdict

    # Parse indices
    indices = []
    try:
        for part in prompt_indices.split(','):
            part = part.strip()
            if '-' in part:
                # Range: 3-6 means [3, 4, 5, 6]
                start, end = part.split('-')
                indices.extend(range(int(start), int(end) + 1))
            else:
                # Single index
                indices.append(int(part))
    except ValueError:
        console.print(f"[red]Invalid index format. Use: 3 or 3,4,5 or 3-6[/red]")
        return

    for p in list_presets():
        if p.get("name", "").lower() == preset_name.lower():
            preset = get_preset(p["id"])
            if not preset:
                console.print(f"[red]Failed to load preset[/red]")
                return

            toggled = []
            invalid = []

            for idx in indices:
                if idx < 0 or idx >= len(preset.data.prompts):
                    invalid.append(idx)
                    continue

                # Toggle the enabled state
                preset.data.prompts[idx].enabled = not preset.data.prompts[idx].enabled
                prompt_name = preset.data.prompts[idx].name or preset.data.prompts[idx].identifier
                status = "enabled" if preset.data.prompts[idx].enabled else "disabled"
                toggled.append(f"{prompt_name} ({status})")

            if invalid:
                console.print(f"[yellow]Warning: Invalid indices skipped: {invalid}[/yellow]")

            if not toggled:
                console.print(f"[red]No valid prompts to toggle[/red]")
                return

            # Save the updated preset
            _write_json(_preset_dir() / f"{preset.id}.json", asdict(preset))

            console.print(f"[green]✓[/green] Toggled {len(toggled)} prompt(s):")
            for item in toggled:
                console.print(f"  • {item}")
            return
    console.print(f"[red]Preset not found: {preset_name}[/red]")


@preset_app.command("enable-all")
def preset_enable_all(
    preset_name: str = typer.Argument(..., help="Preset name"),
    role: str = typer.Option(None, "--role", "-r", help="Only enable prompts with this role (system/user/assistant)"),
):
    """Enable all (or filtered) prompt entries in a preset."""
    from nanobot.sillytavern.storage import list_presets, get_preset, _preset_dir, _write_json
    from dataclasses import asdict

    for p in list_presets():
        if p.get("name", "").lower() == preset_name.lower():
            preset = get_preset(p["id"])
            if not preset:
                console.print(f"[red]Failed to load preset[/red]")
                return

            count = 0
            for prompt in preset.data.prompts:
                if role and prompt.role.lower() != role.lower():
                    continue
                if not prompt.enabled:
                    prompt.enabled = True
                    count += 1

            if count == 0:
                console.print(f"[dim]No prompts changed (all matching prompts already enabled)[/dim]")
                return

            # Save the updated preset
            _write_json(_preset_dir() / f"{preset.id}.json", asdict(preset))

            filter_msg = f" with role '{role}'" if role else ""
            console.print(f"[green]✓[/green] Enabled {count} prompt(s){filter_msg}")
            return
    console.print(f"[red]Preset not found: {preset_name}[/red]")


@preset_app.command("disable-all")
def preset_disable_all(
    preset_name: str = typer.Argument(..., help="Preset name"),
    role: str = typer.Option(None, "--role", "-r", help="Only disable prompts with this role (system/user/assistant)"),
):
    """Disable all (or filtered) prompt entries in a preset."""
    from nanobot.sillytavern.storage import list_presets, get_preset, _preset_dir, _write_json
    from dataclasses import asdict

    for p in list_presets():
        if p.get("name", "").lower() == preset_name.lower():
            preset = get_preset(p["id"])
            if not preset:
                console.print(f"[red]Failed to load preset[/red]")
                return

            count = 0
            for prompt in preset.data.prompts:
                if role and prompt.role.lower() != role.lower():
                    continue
                if prompt.enabled:
                    prompt.enabled = False
                    count += 1

            if count == 0:
                console.print(f"[dim]No prompts changed (all matching prompts already disabled)[/dim]")
                return

            # Save the updated preset
            _write_json(_preset_dir() / f"{preset.id}.json", asdict(preset))

            filter_msg = f" with role '{role}'" if role else ""
            console.print(f"[green]✓[/green] Disabled {count} prompt(s){filter_msg}")
            return
    console.print(f"[red]Preset not found: {preset_name}[/red]")


@preset_app.command("delete")
def preset_delete(name: str = typer.Argument(..., help="Preset name")):
    """Delete a preset."""
    from nanobot.sillytavern.storage import list_presets, delete_preset

    for p in list_presets():
        if p.get("name", "").lower() == name.lower():
            if typer.confirm(f"Delete '{p.get('name')}'?"):
                delete_preset(p["id"])
                console.print(f"[green]✓[/green] Deleted: {p.get('name')}")
            return
    console.print(f"[red]Preset not found: {name}[/red]")


# ============================================================================
# Status
# ============================================================================

@st_app.command("status")
def st_status():
    """Show SillyTavern status."""
    from nanobot.sillytavern.storage import get_status

    status = get_status()

    console.print("[bold]🎭 SillyTavern Status[/bold]\n")
    console.print(f"Characters: {status['characters']}")
    if status["active_character"]:
        console.print(f"  Active: [cyan]{status['active_character']}[/cyan]")
    console.print(f"World Info: {status['world_info_books']} books ({status['world_info_enabled']} enabled)")
    console.print(f"Presets: {status['presets']}")
    if status["active_preset"]:
        console.print(f"  Active: [cyan]{status['active_preset']}[/cyan]")
