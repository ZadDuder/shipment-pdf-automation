"""Telegram bot for uploading shipment documents to /opt/tg_uploads/<company>/<shipment>/.

Flow: company -> shipment number -> file type (inv/pac/batch) -> upload batch -> back to file type menu.
Writes manifest.json next to the saved files. Sends webhook to n8n on /done.
"""
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from submission_validation import validate_submission

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tg-upload-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/opt/tg_uploads"))
N8N_WEBHOOK_URL = os.environ["N8N_WEBHOOK_URL"]
_allowed = os.environ.get("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {int(x) for x in re.split(r"[,\s]+", _allowed) if x} if _allowed else set()

COMPANIES = ["moil", "moroccanoil", "bandi"]
DOC_TYPES = [
    ("inv", "Invoice (inv)"),
    ("pac", "Packing (pac)"),
    ("batch", "Batch"),
]


class Flow(StatesGroup):
    company = State()
    shipment = State()
    menu = State()
    uploading = State()


@dataclass
class ShipmentSession:
    company: str
    shipment_key: str
    folder: Path
    counts: Dict[str, int] = field(default_factory=lambda: {"inv": 0, "pac": 0, "batch": 0})
    files: List[dict] = field(default_factory=list)

    @property
    def manifest_path(self) -> Path:
        return self.folder / "manifest.json"

    def write_manifest(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "company": self.company,
            "shipment_key": self.shipment_key,
            "created_at": int(time.time()),
            "files": self.files,
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)


# ---------- Auth ----------
def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


async def _deny(message: Message) -> None:
    await message.answer("Доступ запрещён. Сообщите админу свой ID: /myid")


# ---------- Keyboards ----------
def kb_companies() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=c.upper(), callback_data=f"company:{c}")] for c in COMPANIES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_doc_types(counts: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for code, label in DOC_TYPES:
        n = counts.get(code, 0)
        text = f"{label} ({n} загружено)" if n else label
        rows.append([InlineKeyboardButton(text=text, callback_data=f"type:{code}")])
    rows.append([InlineKeyboardButton(text="🔄 Статус", callback_data="status")])
    rows.append([
        InlineKeyboardButton(text="✅ Готово (отправить)", callback_data="done"),
    ])
    rows.append([
        InlineKeyboardButton(text="↩️ Поменять поставку", callback_data="change_shipment"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_uploading() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ К выбору типа", callback_data="back_to_menu"),
    ]])


# ---------- Helpers ----------
def _format_status(s: ShipmentSession) -> str:
    return (
        f"📦 *{s.company.upper()}* / поставка `{s.shipment_key}`\n"
        f"Папка: `{s.folder}`\n"
        f"Загружено: inv={s.counts['inv']}, pac={s.counts['pac']}, batch={s.counts['batch']}"
    )


async def _load_session(state: FSMContext) -> Optional[ShipmentSession]:
    data = await state.get_data()
    raw = data.get("session")
    if not raw:
        return None
    s = ShipmentSession(
        company=raw["company"],
        shipment_key=raw["shipment_key"],
        folder=Path(raw["folder"]),
        counts=raw.get("counts", {"inv": 0, "pac": 0, "batch": 0}),
        files=raw.get("files", []),
    )
    return s


async def _save_session(state: FSMContext, s: ShipmentSession) -> None:
    await state.update_data(session={
        "company": s.company,
        "shipment_key": s.shipment_key,
        "folder": str(s.folder),
        "counts": s.counts,
        "files": s.files,
    })


def _safe_shipment_key(text: str) -> Optional[str]:
    t = text.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", t):
        return None
    return t


def _ext_for(message: Message) -> str:
    if message.document and message.document.file_name:
        ext = Path(message.document.file_name).suffix.lower().lstrip(".")
        if ext:
            return ext
    if message.document and message.document.mime_type:
        mime = message.document.mime_type.lower()
        if "pdf" in mime:
            return "pdf"
        if "sheet" in mime or "excel" in mime:
            return "xlsx"
    return "bin"


# ---------- Router ----------
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _deny(message)
    await state.clear()
    await state.set_state(Flow.company)
    await message.answer(
        "Привет! Выберите компанию:",
        reply_markup=kb_companies(),
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: `{message.from_user.id}`")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _deny(message)
    await state.clear()
    await message.answer("Сброшено. /start чтобы начать заново.")


@router.message(Command("done"))
async def cmd_done(message: Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _deny(message)
    await _do_done(message, state)


@router.callback_query(F.data.startswith("company:"))
async def on_company(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_allowed(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    company = cb.data.split(":", 1)[1]
    if company not in COMPANIES:
        return await cb.answer("Неизвестная компания", show_alert=True)
    await state.update_data(company=company)
    await state.set_state(Flow.shipment)
    await cb.message.edit_text(
        f"Компания: *{company.upper()}*\n\nВведите номер поставки (буквы/цифры/дефис, до 64 символов):",
    )
    await cb.answer()


@router.message(Flow.shipment, F.text)
async def on_shipment_text(message: Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _deny(message)
    key = _safe_shipment_key(message.text or "")
    if not key:
        return await message.answer(
            "Неверный формат. Допустимы латинские буквы, цифры, `_` и `-`. Введите ещё раз:"
        )
    data = await state.get_data()
    company = data.get("company")
    if not company:
        await state.clear()
        return await message.answer("Сессия потеряна, начните /start.")
    folder = UPLOAD_ROOT / company / key
    folder.mkdir(parents=True, exist_ok=True)
    s = ShipmentSession(company=company, shipment_key=key, folder=folder)
    # If there is an existing manifest, preload counts so user can continue an upload session.
    if s.manifest_path.exists():
        try:
            existing = json.loads(s.manifest_path.read_text(encoding="utf-8"))
            s.files = existing.get("files", []) or []
            for f in s.files:
                t = f.get("doc_type")
                if t in s.counts:
                    s.counts[t] += 1
        except Exception as e:
            log.warning("Failed to preload manifest %s: %s", s.manifest_path, e)
    await _save_session(state, s)
    await state.set_state(Flow.menu)
    await message.answer(
        _format_status(s) + "\n\nВыберите тип файлов для загрузки:",
        reply_markup=kb_doc_types(s.counts),
    )


@router.callback_query(F.data == "status")
async def on_status(cb: CallbackQuery, state: FSMContext) -> None:
    s = await _load_session(state)
    if not s:
        return await cb.answer("Сессия пуста", show_alert=True)
    await cb.message.edit_text(
        _format_status(s) + "\n\nВыберите тип файлов для загрузки:",
        reply_markup=kb_doc_types(s.counts),
    )
    await cb.answer("Обновлено")


@router.callback_query(F.data == "change_shipment")
async def on_change_shipment(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    company = data.get("company")
    if not company:
        await state.clear()
        return await cb.message.edit_text("Сессия потеряна, начните /start.")
    await state.set_state(Flow.shipment)
    await state.update_data(session=None)
    await cb.message.edit_text(
        f"Компания: *{company.upper()}*\n\nВведите новый номер поставки:"
    )
    await cb.answer()


@router.callback_query(F.data == "cancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Сброшено. /start чтобы начать заново.")
    await cb.answer()


@router.callback_query(F.data == "back_to_menu")
async def on_back_to_menu(cb: CallbackQuery, state: FSMContext) -> None:
    s = await _load_session(state)
    if not s:
        return await cb.answer("Сессия пуста", show_alert=True)
    await state.set_state(Flow.menu)
    await state.update_data(current_doc_type=None, last_upload_ts=0)
    await cb.message.edit_text(
        _format_status(s) + "\n\nВыберите тип файлов:",
        reply_markup=kb_doc_types(s.counts),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("type:"))
async def on_type(cb: CallbackQuery, state: FSMContext) -> None:
    s = await _load_session(state)
    if not s:
        return await cb.answer("Сессия пуста", show_alert=True)
    code = cb.data.split(":", 1)[1]
    if code not in {c for c, _ in DOC_TYPES}:
        return await cb.answer("Неизвестный тип", show_alert=True)
    await state.update_data(current_doc_type=code, last_upload_ts=0)
    await state.set_state(Flow.uploading)
    await cb.message.edit_text(
        _format_status(s)
        + f"\n\nЗагрузите файлы типа *{code}* (можно пачкой/альбомом).\n"
          "Когда закончите этот тип — нажмите «К выбору типа».",
        reply_markup=kb_uploading(),
    )
    await cb.answer()


@router.message(Flow.uploading, F.document)
async def on_document(message: Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _deny(message)
    s = await _load_session(state)
    if not s:
        await state.clear()
        return await message.answer("Сессия потеряна, начните /start.")
    data = await state.get_data()
    code: Optional[str] = data.get("current_doc_type")
    if not code:
        return await message.answer("Сначала выберите тип файла в меню.")

    doc = message.document
    ext = _ext_for(message)
    idx = s.counts.get(code, 0) + 1
    saved_name = f"{s.company}-{code}-{s.shipment_key}-{idx}.{ext}"
    saved_path = s.folder / saved_name
    bot: Bot = message.bot
    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=str(saved_path))
    except Exception as e:
        log.exception("Download failed")
        return await message.answer(f"Не удалось скачать файл: {e}")

    s.counts[code] = idx
    s.files.append({
        "saved_name": saved_name,
        "saved_path": str(saved_path),
        "original_name": doc.file_name or "",
        "doc_type": code,
        "invoice_scope": None,
        "size": doc.file_size or 0,
        "uploaded_at": int(time.time()),
    })
    s.write_manifest()
    await _save_session(state, s)

    # Auto-return to type-selection menu after the user pauses uploading (debounced).
    now = time.time()
    await state.update_data(last_upload_ts=now)

    await message.answer(
        f"✓ {saved_name}  ({code}: {idx})",
    )

    async def _maybe_return_to_menu(saved_ts: float) -> None:
        await asyncio.sleep(2.5)
        d = await state.get_data()
        if d.get("last_upload_ts") != saved_ts:
            return
        cur = await state.get_state()
        if cur != Flow.uploading.state:
            return
        s2 = await _load_session(state)
        if not s2:
            return
        await state.set_state(Flow.menu)
        await state.update_data(current_doc_type=None)
        await message.answer(
            _format_status(s2) + "\n\nВыберите тип файлов:",
            reply_markup=kb_doc_types(s2.counts),
        )

    asyncio.create_task(_maybe_return_to_menu(now))


@router.message(Flow.uploading)
async def on_uploading_text(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        return  # commands handled elsewhere
    await message.answer("Жду документ. Если закончили этот тип — нажмите «К выбору типа».")


@router.callback_query(F.data == "done")
async def on_done_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await _do_done(cb.message, state, user_id=cb.from_user.id)
    await cb.answer()


async def _do_done(message: Message, state: FSMContext, user_id: Optional[int] = None) -> None:
    s = await _load_session(state)
    if not s:
        return await message.answer("Нет активной поставки. /start.")
    if not s.files:
        return await message.answer("Не загружено ни одного файла. Загрузите хотя бы один.")
    validation_error = validate_submission(s.company, s.counts)
    if validation_error:
        return await message.answer(validation_error)
    s.write_manifest()
    payload = {
        "company": s.company,
        # snake_case keys are what the n8n Normalize Bot Payload node expects;
        # camelCase duplicates kept for backward compat with older workflow versions.
        "shipment_number": s.shipment_key,
        "shipment_dir": str(s.folder),
        "manifest_path": str(s.manifest_path),
        "user_id": message.chat.id,
        "username": (message.from_user.username if message.from_user else None),
        "files": s.files,
        "total_files": len(s.files),
        "shipmentKey": s.shipment_key,
        "shipmentDir": str(s.folder),
        "manifestPath": str(s.manifest_path),
        "chatId": message.chat.id,
        "totalFiles": len(s.files),
    }
    log.info("Sending webhook for %s/%s, files=%d", s.company, s.shipment_key, len(s.files))
    await message.answer(
        f"📤 Отправляю в обработку: {s.company.upper()} / {s.shipment_key} ({len(s.files)} файлов)…"
    )
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as http:
            async with http.post(N8N_WEBHOOK_URL, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    await message.answer(f"⚠️ n8n ответил {resp.status}:\n{text[:500]}")
                else:
                    await message.answer("✅ Принято к обработке. n8n пришлёт summary.")
    except Exception as e:
        log.exception("Webhook failed")
        await message.answer(f"❌ Не удалось отправить webhook: {e}")
    await state.clear()


async def main() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    log.info("Bot starting. UPLOAD_ROOT=%s, allowed=%s", UPLOAD_ROOT, ALLOWED_USER_IDS or "ALL")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
