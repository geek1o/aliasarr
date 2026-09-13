"""
Каталог заготовленных шаблонов озвучек и студий перевода для профилей качества Aliasarr.
Содержит 44 оптимизированных регулярных выражения для распознавания студий в названиях релизов.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, TypedDict


class VoiceoverPreset(TypedDict):
    id: str
    name: str
    category: str
    regex: str
    example: str


VOICEOVER_PRESETS: List[VoiceoverPreset] = [
    # -------------------------------------------------------------------------
    # Сериалы и Кино (14 студий)
    # -------------------------------------------------------------------------
    {
        "id": "lostfilm",
        "name": "LostFilm",
        "category": "series_movies",
        "regex": r"\b(lostfilm|lost[-_. ]?film|лостфильм)\b",
        "example": "House of the Dragon S02E01 1080p LostFilm",
    },
    {
        "id": "kubik_v_kube",
        "name": "Кубик в кубе",
        "category": "series_movies",
        "regex": r"\b(kubik[-_. ]?v[-_. ]?kube|kubik|кубик[-_. ]*в[-_. ]*кубе|квк)\b",
        "example": "The Boys S04E01 1080p Кубик в кубе",
    },
    {
        "id": "newstudio",
        "name": "NewStudio",
        "category": "series_movies",
        "regex": r"\b(newstudio|new[-_. ]?studio|ньюстудио|ньюстудия)\b",
        "example": "Fargo S05E01 1080p NewStudio",
    },
    {
        "id": "alexfilm",
        "name": "AlexFilm",
        "category": "series_movies",
        "regex": r"\b(alexfilm|alex[-_. ]?film|алексфильм)\b",
        "example": "Peaky Blinders S06 1080p AlexFilm",
    },
    {
        "id": "baibako",
        "name": "BaibaKo",
        "category": "series_movies",
        "regex": r"\b(baibako(?:tv)?|байбако)\b",
        "example": "Doctor Who S14E01 1080p BaibaKo",
    },
    {
        "id": "kuraj_bambey",
        "name": "Кураж-Бамбей",
        "category": "series_movies",
        "regex": r"\b(kuraj[-_. ]?bambey|кураж[-_. ]?бамбей|kuraj)\b",
        "example": "The Big Bang Theory S12 1080p Кураж-Бамбей",
    },
    {
        "id": "amedia",
        "name": "Amedia / Амедиа",
        "category": "series_movies",
        "regex": r"\b(amedia(?:teka)?|амедиа(?:тека)?)\b",
        "example": "Succession S04 1080p Amedia",
    },
    {
        "id": "jaskier",
        "name": "Jaskier",
        "category": "series_movies",
        "regex": r"\b(jaskier|яскьер)\b",
        "example": "The Witcher S03 1080p Jaskier",
    },
    {
        "id": "hdrezka_studio",
        "name": "HDrezka Studio",
        "category": "series_movies",
        "regex": r"\b(hdrezka|hd[-_. ]?rezka|rezka|хдрезка|резка)\b",
        "example": "Shogun S01E01 1080p HDrezka Studio",
    },
    {
        "id": "tvshows",
        "name": "TVShows",
        "category": "series_movies",
        "regex": r"\b(tvshows|tv[-_. ]?shows|твшоуз)\b",
        "example": "Loki S02 1080p TVShows",
    },
    {
        "id": "viruseproject",
        "name": "ViruseProject",
        "category": "series_movies",
        "regex": r"\b(viruse[-_. ]?project|вирус[-_. ]?проджект)\b",
        "example": "Dark S03 1080p ViruseProject",
    },
    {
        "id": "goblin",
        "name": "Гоблин",
        "category": "series_movies",
        "regex": r"\b(goblin|гоблин|пучков|дмитрий[-_. ]?пучков)\b",
        "example": "Snatch 2000 1080p Goblin",
    },
    {
        "id": "coldfilm",
        "name": "ColdFilm",
        "category": "series_movies",
        "regex": r"\b(coldfilm|cold[-_. ]?film|колдфильм)\b",
        "example": "Severance S01 1080p ColdFilm",
    },
    {
        "id": "newcomers",
        "name": "NewComers",
        "category": "series_movies",
        "regex": r"\b(newcomers|new[-_. ]?comers|ньюкамерс)\b",
        "example": "The Bear S02 1080p NewComers",
    },

    # -------------------------------------------------------------------------
    # Аниме (30 студий)
    # -------------------------------------------------------------------------
    {
        "id": "anilibria",
        "name": "AniLibria",
        "category": "anime",
        "regex": r"\b(anilibria|анилибрия)\b",
        "example": "[AniLibria] Jujutsu Kaisen S02 1080p",
    },
    {
        "id": "anidub",
        "name": "AniDUB",
        "category": "anime",
        "regex": r"\b(anidub|анидаб)\b",
        "example": "[AniDUB] Naruto Shippuden 1080p",
    },
    {
        "id": "shiza_project",
        "name": "SHIZA Project",
        "category": "anime",
        "regex": r"\b(shiza[-_. ]?project|shiza|шиза[-_. ]?проджект|шиза)\b",
        "example": "[SHIZA Project] Bleach TYBW 1080p",
    },
    {
        "id": "studio_band",
        "name": "Студийная банда",
        "category": "anime",
        "regex": r"\b(studio[-_. ]?band|студийная[-_. ]?банда)\b",
        "example": "Chainsaw Man S01 1080p Studio Band",
    },
    {
        "id": "cuba77",
        "name": "Cuba77",
        "category": "anime",
        "regex": r"\b(cuba77|куба77)\b",
        "example": "One Piece 1080p Cuba77",
    },
    {
        "id": "animevost",
        "name": "AnimeVost",
        "category": "anime",
        "regex": r"\b(animevost|anime[-_. ]?vost|анимевост)\b",
        "example": "[AnimeVost] Solo Leveling S01 1080p",
    },
    {
        "id": "anistar",
        "name": "AniStar",
        "category": "anime",
        "regex": r"\b(anistar|ani[-_. ]?star|анистар)\b",
        "example": "[AniStar] Black Clover 1080p",
    },
    {
        "id": "animedia",
        "name": "AniMedia",
        "category": "anime",
        "regex": r"\b(animedia|ani[-_. ]?media|анимедиа)\b",
        "example": "[AniMedia] Demon Slayer S03 1080p",
    },
    {
        "id": "anilibria_subtitles",
        "name": "AniLibria.Subtitles",
        "category": "anime",
        "regex": r"\b(anilibria[-_. ]?(?:subtitles|subs|субтитры)|анилибрия[-_. ]?(?:субтитры|сабы))\b",
        "example": "[AniLibria.Subtitles] Frieren 1080p",
    },
    {
        "id": "anisound",
        "name": "AniSound",
        "category": "anime",
        "regex": r"\b(anisound|ani[-_. ]?sound|анисаунд)\b",
        "example": "[AniSound] Mashle S02 1080p",
    },
    {
        "id": "aniplay",
        "name": "AniPlay",
        "category": "anime",
        "regex": r"\b(aniplay|ani[-_. ]?play|аниплей)\b",
        "example": "[AniPlay] Oshi no Ko S02 1080p",
    },
    {
        "id": "animaunt",
        "name": "AniMaunt",
        "category": "anime",
        "regex": r"\b(animaunt|ani[-_. ]?maunt|анимаунт)\b",
        "example": "[AniMaunt] Blue Lock S01 1080p",
    },
    {
        "id": "ancord",
        "name": "Ancord",
        "category": "anime",
        "regex": r"\b(ancord|анкорд)\b",
        "example": "Fairy Tail 1080p Ancord",
    },
    {
        "id": "persona99",
        "name": "Persona99",
        "category": "anime",
        "regex": r"\b(persona[-_. ]?99|персона[-_. ]?99)\b",
        "example": "Gundam 1080p Persona99",
    },
    {
        "id": "eladiel",
        "name": "Eladiel",
        "category": "anime",
        "regex": r"\b(eladiel|эладиэль)\b",
        "example": "Steins Gate 1080p Eladiel",
    },
    {
        "id": "jam",
        "name": "JAM",
        "category": "anime",
        "regex": r"\b(jam(?:[-_. ]?club)?|джем)\b",
        "example": "[JAM] Attack on Titan Final 1080p",
    },
    {
        "id": "animur",
        "name": "AniMur",
        "category": "anime",
        "regex": r"\b(animur|ani[-_. ]?mur|анимур)\b",
        "example": "[AniMur] Haikyuu Movie 1080p",
    },
    {
        "id": "anisky",
        "name": "AniSky",
        "category": "anime",
        "regex": r"\b(anisky|ani[-_. ]?sky|анискай)\b",
        "example": "[AniSky] Wind Breaker S01 1080p",
    },
    {
        "id": "dream_cast",
        "name": "Dream Cast",
        "category": "anime",
        "regex": r"\b(dream[-_. ]?cast|дрим[-_. ]?каст)\b",
        "example": "[Dream Cast] Kaiju No 8 1080p",
    },
    {
        "id": "anything_group",
        "name": "Anything Group",
        "category": "anime",
        "regex": r"\b(anything[-_. ]?group|энисинг[-_. ]?групп)\b",
        "example": "[Anything Group] Vinland Saga S02 1080p",
    },
    {
        "id": "aos_team",
        "name": "AOS Team",
        "category": "anime",
        "regex": r"\b(aos[-_. ]?team|aos)\b",
        "example": "[AOS Team] Hell Paradise 1080p",
    },
    {
        "id": "anifilm",
        "name": "AniFilm",
        "category": "anime",
        "regex": r"\b(anifilm|ani[-_. ]?film|анифильм)\b",
        "example": "[AniFilm] Spy x Family S02 1080p",
    },
    {
        "id": "sovetromantica",
        "name": "SovetRomantica",
        "category": "anime",
        "regex": r"\b(sovet[-_. ]?romantica|совет[-_. ]?романтика)\b",
        "example": "[SovetRomantica] Horimiya 1080p",
    },
    {
        "id": "onibaku",
        "name": "Onibaku",
        "category": "anime",
        "regex": r"\b(onibaku(?:[-_. ]?group)?|онибаку)\b",
        "example": "[Onibaku] Great Teacher Onizuka 1080p",
    },
    {
        "id": "anime_heaven",
        "name": "Anime Heaven",
        "category": "anime",
        "regex": r"\b(anime[-_. ]?heaven|аниме[-_. ]?х[еэ]вен)\b",
        "example": "[Anime Heaven] DanMachi S05 1080p",
    },
    {
        "id": "animato",
        "name": "AniMato",
        "category": "anime",
        "regex": r"\b(animato|ani[-_. ]?mato|анимато)\b",
        "example": "[AniMato] Dr Stone S03 1080p",
    },
    {
        "id": "aniversal",
        "name": "AniVersal",
        "category": "anime",
        "regex": r"\b(aniversal|ani[-_. ]?versal|аниверсал)\b",
        "example": "[AniVersal] Overlord S04 1080p",
    },
    {
        "id": "reanimedia",
        "name": "Reanimedia",
        "category": "anime",
        "regex": r"\b(reanimedia|реанимедиа)\b",
        "example": "Gurren Lagann 1080p Reanimedia",
    },
    {
        "id": "mc_entertainment",
        "name": "MC Entertainment",
        "category": "anime",
        "regex": r"\b(mc[-_. ]?entertainment|mcent|эмси[-_. ]?энтертейнмент)\b",
        "example": "Evangelion 1080p MC Entertainment",
    },
    {
        "id": "crunchyroll",
        "name": "Crunchyroll",
        "category": "anime",
        "regex": r"\b(crunchyroll|кранчиролл)\b",
        "example": "Jujutsu Kaisen S02 1080p Crunchyroll",
    },
]

VOICEOVER_PRESET_BY_NAME: Dict[str, VoiceoverPreset] = {
    p["name"]: p for p in VOICEOVER_PRESETS
}

VOICEOVER_PRESET_BY_ID: Dict[str, VoiceoverPreset] = {
    p["id"]: p for p in VOICEOVER_PRESETS
}


def find_preset_by_regex(pattern: Optional[str]) -> Optional[VoiceoverPreset]:
    """
    Определяет пресет озвучки по строке регулярного выражения (с нормализацией пробелов/регистра).
    """
    if not pattern:
        return None
    cleaned = pattern.strip()
    for preset in VOICEOVER_PRESETS:
        if preset["regex"] == cleaned:
            return preset
        # Поиск по нормализованному шаблону без пробелов
        if preset["regex"].replace(" ", "") == cleaned.replace(" ", ""):
            return preset
    return None
