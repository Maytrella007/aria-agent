"""
ARIA - Language System
=======================
Multilingual support for ARIA.
ARIA can communicate in the user's preferred language.

Supports the 10 most spoken languages in the world.
"""

import os
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# Try to import memory system for persistence
try:
    from .utils import atomic_write_yaml, safe_yaml_load
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False


class Language(Enum):
    """Supported languages - Top 10 most spoken"""
    ENGLISH = "en"
    CHINESE = "zh"
    HINDI = "hi"
    SPANISH = "es"
    FRENCH = "fr"
    ARABIC = "ar"
    BENGALI = "bn"
    PORTUGUESE = "pt"
    RUSSIAN = "ru"
    JAPANESE = "ja"


# Language metadata
LANGUAGE_INFO = {
    Language.ENGLISH: {
        "name": "English",
        "native_name": "English",
        "flag": "🇬🇧",
        "greeting": "Hello",
    },
    Language.CHINESE: {
        "name": "Chinese (Mandarin)",
        "native_name": "中文 (普通话)",
        "flag": "🇨🇳",
        "greeting": "你好",
    },
    Language.HINDI: {
        "name": "Hindi",
        "native_name": "हिन्दी",
        "flag": "🇮🇳",
        "greeting": "नमस्ते",
    },
    Language.SPANISH: {
        "name": "Spanish",
        "native_name": "Español",
        "flag": "🇪🇸",
        "greeting": "Hola",
    },
    Language.FRENCH: {
        "name": "French",
        "native_name": "Français",
        "flag": "🇫🇷",
        "greeting": "Bonjour",
    },
    Language.ARABIC: {
        "name": "Arabic",
        "native_name": "العربية",
        "flag": "🇸🇦",
        "greeting": "مرحبا",
    },
    Language.BENGALI: {
        "name": "Bengali",
        "native_name": "বাংলা",
        "flag": "🇧🇩",
        "greeting": "হ্যালো",
    },
    Language.PORTUGUESE: {
        "name": "Portuguese",
        "native_name": "Português",
        "flag": "🇧🇷",
        "greeting": "Olá",
    },
    Language.RUSSIAN: {
        "name": "Russian",
        "native_name": "Русский",
        "flag": "🇷🇺",
        "greeting": "Привет",
    },
    Language.JAPANESE: {
        "name": "Japanese",
        "native_name": "日本語",
        "flag": "🇯🇵",
        "greeting": "こんにちは",
    },
}


# ============================================
# TRANSLATIONS
# ============================================

TRANSLATIONS = {
    # Language selection prompt
    "select_language_title": {
        "en": "SELECT YOUR LANGUAGE",
        "zh": "选择您的语言",
        "hi": "अपनी भाषा चुनें",
        "es": "SELECCIONA TU IDIOMA",
        "fr": "SÉLECTIONNEZ VOTRE LANGUE",
        "ar": "اختر لغتك",
        "bn": "আপনার ভাষা নির্বাচন করুন",
        "pt": "SELECIONE SEU IDIOMA",
        "ru": "ВЫБЕРИТЕ ВАШ ЯЗЫК",
        "ja": "言語を選択してください",
    },
    "select_language_prompt": {
        "en": "Enter the number of your preferred language",
        "zh": "输入您首选语言的编号",
        "hi": "अपनी पसंदीदा भाषा का नंबर दर्ज करें",
        "es": "Ingresa el número de tu idioma preferido",
        "fr": "Entrez le numéro de votre langue préférée",
        "ar": "أدخل رقم لغتك المفضلة",
        "bn": "আপনার পছন্দের ভাষার নম্বর লিখুন",
        "pt": "Digite o número do seu idioma preferido",
        "ru": "Введите номер вашего предпочтительного языка",
        "ja": "ご希望の言語の番号を入力してください",
    },
    "save_preference_question": {
        "en": "Would you like to save this language preference for future sessions?",
        "zh": "您想保存此语言偏好以供将来使用吗？",
        "hi": "क्या आप भविष्य के सत्रों के लिए इस भाषा प्राथमिकता को सहेजना चाहेंगे?",
        "es": "¿Deseas guardar esta preferencia de idioma para futuras sesiones?",
        "fr": "Souhaitez-vous enregistrer cette préférence linguistique pour les sessions futures?",
        "ar": "هل تريد حفظ تفضيل اللغة هذا للجلسات المستقبلية؟",
        "bn": "আপনি কি ভবিষ্যতের সেশনের জন্য এই ভাষা পছন্দ সংরক্ষণ করতে চান?",
        "pt": "Deseja salvar esta preferência de idioma para sessões futuras?",
        "ru": "Хотите сохранить этот языковой параметр для будущих сеансов?",
        "ja": "この言語設定を今後のセッション用に保存しますか？",
    },
    "yes_save": {
        "en": "Yes, remember my preference",
        "zh": "是的，记住我的偏好",
        "hi": "हाँ, मेरी प्राथमिकता याद रखें",
        "es": "Sí, recordar mi preferencia",
        "fr": "Oui, mémoriser ma préférence",
        "ar": "نعم، تذكر تفضيلي",
        "bn": "হ্যাঁ, আমার পছন্দ মনে রাখুন",
        "pt": "Sim, lembrar minha preferência",
        "ru": "Да, запомнить мои предпочтения",
        "ja": "はい、設定を保存する",
    },
    "no_this_session": {
        "en": "No, only for this session",
        "zh": "不，仅限本次会话",
        "hi": "नहीं, केवल इस सत्र के लिए",
        "es": "No, solo para esta sesión",
        "fr": "Non, seulement pour cette session",
        "ar": "لا، لهذه الجلسة فقط",
        "bn": "না, শুধুমাত্র এই সেশনের জন্য",
        "pt": "Não, apenas para esta sessão",
        "ru": "Нет, только для этого сеанса",
        "ja": "いいえ、このセッションのみ",
    },
    "language_saved": {
        "en": "Language preference saved! I'll remember to speak {language} with you.",
        "zh": "语言偏好已保存！我会记得用{language}与您交流。",
        "hi": "भाषा प्राथमिकता सहेजी गई! मैं आपसे {language} में बात करना याद रखूंगा।",
        "es": "¡Preferencia de idioma guardada! Recordaré hablarte en {language}.",
        "fr": "Préférence linguistique enregistrée! Je me souviendrai de vous parler en {language}.",
        "ar": "تم حفظ تفضيل اللغة! سأتذكر التحدث معك بـ {language}.",
        "bn": "ভাষা পছন্দ সংরক্ষিত! আমি আপনার সাথে {language} ভাষায় কথা বলতে মনে রাখব।",
        "pt": "Preferência de idioma salva! Vou lembrar de falar {language} com você.",
        "ru": "Языковые предпочтения сохранены! Я буду помнить, что нужно говорить с вами на {language}.",
        "ja": "言語設定を保存しました！{language}でお話しすることを覚えておきます。",
    },
    "language_session_only": {
        "en": "Got it! I'll speak {language} for this session only.",
        "zh": "明白了！我将在本次会话中使用{language}。",
        "hi": "समझ गया! मैं केवल इस सत्र के लिए {language} बोलूंगा।",
        "es": "¡Entendido! Hablaré {language} solo para esta sesión.",
        "fr": "Compris! Je parlerai {language} uniquement pour cette session.",
        "ar": "فهمت! سأتحدث {language} لهذه الجلسة فقط.",
        "bn": "বুঝেছি! আমি শুধুমাত্র এই সেশনের জন্য {language} বলব।",
        "pt": "Entendi! Vou falar {language} apenas para esta sessão.",
        "ru": "Понял! Я буду говорить на {language} только в этом сеансе.",
        "ja": "わかりました！このセッションでは{language}で話します。",
    },
    "hello_aria": {
        "en": "Hello! I am ARIA.",
        "zh": "你好！我是ARIA。",
        "hi": "नमस्ते! मैं ARIA हूं।",
        "es": "¡Hola! Soy ARIA.",
        "fr": "Bonjour! Je suis ARIA.",
        "ar": "مرحبا! أنا ARIA.",
        "bn": "হ্যালো! আমি ARIA।",
        "pt": "Olá! Eu sou ARIA.",
        "ru": "Привет! Я ARIA.",
        "ja": "こんにちは！私はARIAです。",
    },
    "exit_command": {
        "en": "Type 'exit' to end",
        "zh": "输入 'exit' 结束",
        "hi": "'exit' टाइप करें समाप्त करने के लिए",
        "es": "Escribe 'exit' para terminar",
        "fr": "Tapez 'exit' pour terminer",
        "ar": "اكتب 'exit' للإنهاء",
        "bn": "শেষ করতে 'exit' টাইপ করুন",
        "pt": "Digite 'exit' para sair",
        "ru": "Введите 'exit' для завершения",
        "ja": "'exit'と入力して終了",
    },
    "language_command_hint": {
        "en": "Type '/language' to change language",
        "zh": "输入 '/language' 更改语言",
        "hi": "भाषा बदलने के लिए '/language' टाइप करें",
        "es": "Escribe '/language' para cambiar idioma",
        "fr": "Tapez '/language' pour changer de langue",
        "ar": "اكتب '/language' لتغيير اللغة",
        "bn": "ভাষা পরিবর্তন করতে '/language' টাইপ করুন",
        "pt": "Digite '/language' para mudar o idioma",
        "ru": "Введите '/language' для смены языка",
        "ja": "'/language'と入力して言語を変更",
    },
    "security_command_hint": {
        "en": "Type 'security' to see security status",
        "zh": "输入 'security' 查看安全状态",
        "hi": "सुरक्षा स्थिति देखने के लिए 'security' टाइप करें",
        "es": "Escribe 'security' para ver estado de seguridad",
        "fr": "Tapez 'security' pour voir l'état de sécurité",
        "ar": "اكتب 'security' لرؤية حالة الأمان",
        "bn": "নিরাপত্তা স্থিতি দেখতে 'security' টাইপ করুন",
        "pt": "Digite 'security' para ver status de segurança",
        "ru": "Введите 'security' для просмотра статуса безопасности",
        "ja": "'security'と入力してセキュリティ状態を確認",
    },
    "previous_language_found": {
        "en": "I remember you prefer {language}. Would you like to continue in {language}?",
        "zh": "我记得您偏好{language}。您想继续使用{language}吗？",
        "hi": "मुझे याद है आप {language} पसंद करते हैं। क्या आप {language} में जारी रखना चाहेंगे?",
        "es": "Recuerdo que prefieres {language}. ¿Deseas continuar en {language}?",
        "fr": "Je me souviens que vous préférez {language}. Voulez-vous continuer en {language}?",
        "ar": "أتذكر أنك تفضل {language}. هل تريد الاستمرار بـ {language}؟",
        "bn": "আমার মনে আছে আপনি {language} পছন্দ করেন। আপনি কি {language} এ চালিয়ে যেতে চান?",
        "pt": "Lembro que você prefere {language}. Gostaria de continuar em {language}?",
        "ru": "Я помню, что вы предпочитаете {language}. Хотите продолжить на {language}?",
        "ja": "{language}がお好みだったことを覚えています。{language}で続けますか？",
    },
    "yes": {
        "en": "Yes",
        "zh": "是",
        "hi": "हाँ",
        "es": "Sí",
        "fr": "Oui",
        "ar": "نعم",
        "bn": "হ্যাঁ",
        "pt": "Sim",
        "ru": "Да",
        "ja": "はい",
    },
    "no": {
        "en": "No",
        "zh": "否",
        "hi": "नहीं",
        "es": "No",
        "fr": "Non",
        "ar": "لا",
        "bn": "না",
        "pt": "Não",
        "ru": "Нет",
        "ja": "いいえ",
    },
    "change_language": {
        "en": "No, let me choose another language",
        "zh": "不，让我选择另一种语言",
        "hi": "नहीं, मुझे दूसरी भाषा चुनने दें",
        "es": "No, déjame elegir otro idioma",
        "fr": "Non, laissez-moi choisir une autre langue",
        "ar": "لا، دعني أختار لغة أخرى",
        "bn": "না, আমাকে অন্য ভাষা বেছে নিতে দিন",
        "pt": "Não, deixe-me escolher outro idioma",
        "ru": "Нет, позвольте мне выбрать другой язык",
        "ja": "いいえ、別の言語を選びたいです",
    },
    "language_changed": {
        "en": "Language changed to {language}.",
        "zh": "语言已更改为{language}。",
        "hi": "भाषा {language} में बदल दी गई।",
        "es": "Idioma cambiado a {language}.",
        "fr": "Langue changée en {language}.",
        "ar": "تم تغيير اللغة إلى {language}.",
        "bn": "ভাষা {language} এ পরিবর্তন করা হয়েছে।",
        "pt": "Idioma alterado para {language}.",
        "ru": "Язык изменен на {language}.",
        "ja": "言語を{language}に変更しました。",
    },

    # Security translations
    "security_mode_title": {
        "en": "SECURITY MODE SELECTION",
        "zh": "安全模式选择",
        "hi": "सुरक्षा मोड चयन",
        "es": "SELECCIÓN DE MODO DE SEGURIDAD",
        "fr": "SÉLECTION DU MODE DE SÉCURITÉ",
        "ar": "اختيار وضع الأمان",
        "bn": "নিরাপত্তা মোড নির্বাচন",
        "pt": "SELEÇÃO DE MODO DE SEGURANÇA",
        "ru": "ВЫБОР РЕЖИМА БЕЗОПАСНОСТИ",
        "ja": "セキュリティモード選択",
    },
    "security_free_name": {
        "en": "FREE (No Restrictions)",
        "zh": "自由（无限制）",
        "hi": "मुक्त (कोई प्रतिबंध नहीं)",
        "es": "LIBRE (Sin Restricciones)",
        "fr": "LIBRE (Sans Restrictions)",
        "ar": "حر (بدون قيود)",
        "bn": "মুক্ত (কোন সীমাবদ্ধতা নেই)",
        "pt": "LIVRE (Sem Restrições)",
        "ru": "СВОБОДНЫЙ (Без ограничений)",
        "ja": "フリー（制限なし）",
    },
    "security_protected_name": {
        "en": "PROTECTED (Recommended)",
        "zh": "受保护（推荐）",
        "hi": "संरक्षित (अनुशंसित)",
        "es": "PROTEGIDO (Recomendado)",
        "fr": "PROTÉGÉ (Recommandé)",
        "ar": "محمي (موصى به)",
        "bn": "সুরক্ষিত (প্রস্তাবিত)",
        "pt": "PROTEGIDO (Recomendado)",
        "ru": "ЗАЩИЩЕННЫЙ (Рекомендуется)",
        "ja": "保護（推奨）",
    },
    "security_paranoid_name": {
        "en": "PARANOID (Maximum Security)",
        "zh": "偏执（最高安全）",
        "hi": "पैरानॉयड (अधिकतम सुरक्षा)",
        "es": "PARANOICO (Máxima Seguridad)",
        "fr": "PARANOÏAQUE (Sécurité Maximale)",
        "ar": "بجنون العظمة (أقصى أمان)",
        "bn": "প্যারানয়েড (সর্বোচ্চ নিরাপত্তা)",
        "pt": "PARANOICO (Segurança Máxima)",
        "ru": "ПАРАНОИДАЛЬНЫЙ (Максимальная безопасность)",
        "ja": "パラノイド（最大セキュリティ）",
    },
    "security_warning_free": {
        "en": "⚠️ ARIA can execute ANY command. A single error can destroy your system.",
        "zh": "⚠️ ARIA可以执行任何命令。一个错误就可能破坏您的系统。",
        "hi": "⚠️ ARIA कोई भी कमांड चला सकता है। एक गलती आपके सिस्टम को नष्ट कर सकती है।",
        "es": "⚠️ ARIA puede ejecutar CUALQUIER comando. Un error puede destruir tu sistema.",
        "fr": "⚠️ ARIA peut exécuter N'IMPORTE QUELLE commande. Une erreur peut détruire votre système.",
        "ar": "⚠️ يمكن لـ ARIA تنفيذ أي أمر. خطأ واحد يمكن أن يدمر نظامك.",
        "bn": "⚠️ ARIA যেকোনো কমান্ড চালাতে পারে। একটি ভুল আপনার সিস্টেম ধ্বংস করতে পারে।",
        "pt": "⚠️ ARIA pode executar QUALQUER comando. Um erro pode destruir seu sistema.",
        "ru": "⚠️ ARIA может выполнить ЛЮБУЮ команду. Одна ошибка может уничтожить вашу систему.",
        "ja": "⚠️ ARIAはどんなコマンドでも実行できます。1つのエラーでシステムが破壊される可能性があります。",
    },
    "confirm_free_mode": {
        "en": "Type 'I ACCEPT THE RISK' to confirm",
        "zh": "输入 '我接受风险' 确认",
        "hi": "'मैं जोखिम स्वीकार करता हूं' टाइप करें",
        "es": "Escribe 'ACEPTO EL RIESGO' para confirmar",
        "fr": "Tapez 'J'ACCEPTE LE RISQUE' pour confirmer",
        "ar": "اكتب 'أقبل المخاطرة' للتأكيد",
        "bn": "নিশ্চিত করতে 'আমি ঝুঁকি গ্রহণ করি' টাইপ করুন",
        "pt": "Digite 'ACEITO O RISCO' para confirmar",
        "ru": "Введите 'Я ПРИНИМАЮ РИСК' для подтверждения",
        "ja": "確認するには「リスクを受け入れます」と入力してください",
    },
    "free_mode_confirmations": {
        "en": ["I ACCEPT THE RISK", "YES", "CONFIRM"],
        "zh": ["我接受风险", "是", "确认"],
        "hi": ["मैं जोखिम स्वीकार करता हूं", "हाँ", "पुष्टि"],
        "es": ["ACEPTO EL RIESGO", "SI", "CONFIRMAR"],
        "fr": ["J'ACCEPTE LE RISQUE", "OUI", "CONFIRMER"],
        "ar": ["أقبل المخاطرة", "نعم", "تأكيد"],
        "bn": ["আমি ঝুঁকি গ্রহণ করি", "হ্যাঁ", "নিশ্চিত"],
        "pt": ["ACEITO O RISCO", "SIM", "CONFIRMAR"],
        "ru": ["Я ПРИНИМАЮ РИСК", "ДА", "ПОДТВЕРДИТЬ"],
        "ja": ["リスクを受け入れます", "はい", "確認"],
    },

    # Additional security mode descriptions
    "security_aria_title": {
        "en": "ARIA - SECURITY CONFIGURATION",
        "zh": "ARIA - 安全配置",
        "hi": "ARIA - सुरक्षा विन्यास",
        "es": "ARIA - CONFIGURACIÓN DE SEGURIDAD",
        "fr": "ARIA - CONFIGURATION DE SÉCURITÉ",
        "ar": "ARIA - تكوين الأمان",
        "bn": "ARIA - নিরাপত্তা কনফিগারেশন",
        "pt": "ARIA - CONFIGURAÇÃO DE SEGURANÇA",
        "ru": "ARIA - НАСТРОЙКА БЕЗОПАСНОСТИ",
        "ja": "ARIA - セキュリティ設定",
    },
    "security_intro": {
        "en": "ARIA was designed with total freedom in mind.\nBut freedom comes with responsibility.\n\nPlease choose the security level for this session:",
        "zh": "ARIA 设计时考虑了完全自由。\n但自由伴随着责任。\n\n请为此会话选择安全级别：",
        "hi": "ARIA को पूर्ण स्वतंत्रता के साथ डिज़ाइन किया गया था।\nलेकिन स्वतंत्रता के साथ जिम्मेदारी आती है।\n\nकृपया इस सत्र के लिए सुरक्षा स्तर चुनें：",
        "es": "ARIA fue diseñado con libertad total en mente.\nPero la libertad viene con responsabilidad.\n\nPor favor, elige el nivel de seguridad para esta sesión:",
        "fr": "ARIA a été conçu avec la liberté totale à l'esprit.\nMais la liberté vient avec la responsabilité.\n\nVeuillez choisir le niveau de sécurité pour cette session:",
        "ar": "تم تصميم ARIA مع حرية كاملة في الاعتبار.\nلكن الحرية تأتي مع المسؤولية.\n\nيرجى اختيار مستوى الأمان لهذه الجلسة:",
        "bn": "ARIA সম্পূর্ণ স্বাধীনতার কথা মাথায় রেখে ডিজাইন করা হয়েছে।\nকিন্তু স্বাধীনতার সাথে দায়িত্ব আসে।\n\nঅনুগ্রহ করে এই সেশনের জন্য নিরাপত্তা স্তর চয়ন করুন:",
        "pt": "ARIA foi projetado com liberdade total em mente.\nMas liberdade vem com responsabilidade.\n\nPor favor, escolha o nível de segurança para esta sessão:",
        "ru": "ARIA был разработан с полной свободой.\nНо свобода приходит с ответственностью.\n\nПожалуйста, выберите уровень безопасности для этой сессии:",
        "ja": "ARIAは完全な自由を念頭に設計されました。\nしかし自由には責任が伴います。\n\nこのセッションのセキュリティレベルを選択してください：",
    },
    "security_free_desc": {
        "en": "No restrictions (DANGEROUS)\n    ARIA can do absolutely anything.\n    A single error can destroy your system.",
        "zh": "无限制（危险）\n    ARIA可以做任何事情。\n    一个错误就可能破坏您的系统。",
        "hi": "कोई प्रतिबंध नहीं (खतरनाक)\n    ARIA बिल्कुल कुछ भी कर सकता है।\n    एक गलती आपके सिस्टम को नष्ट कर सकती है।",
        "es": "Sin restricciones (PELIGROSO)\n    ARIA puede hacer absolutamente todo.\n    Un solo error puede destruir tu sistema.",
        "fr": "Sans restrictions (DANGEREUX)\n    ARIA peut faire absolument tout.\n    Une seule erreur peut détruire votre système.",
        "ar": "بدون قيود (خطير)\n    يمكن لـ ARIA فعل أي شيء.\n    خطأ واحد يمكن أن يدمر نظامك.",
        "bn": "কোন সীমাবদ্ধতা নেই (বিপজ্জনক)\n    ARIA একেবারে যেকোনো কিছু করতে পারে।\n    একটি ভুল আপনার সিস্টেম ধ্বংস করতে পারে।",
        "pt": "Sem restrições (PERIGOSO)\n    ARIA pode fazer absolutamente tudo.\n    Um único erro pode destruir seu sistema.",
        "ru": "Без ограничений (ОПАСНО)\n    ARIA может делать абсолютно всё.\n    Одна ошибка может уничтожить вашу систему.",
        "ja": "制限なし（危険）\n    ARIAは何でもできます。\n    1つのエラーでシステムが破壊される可能性があります。",
    },
    "security_protected_desc": {
        "en": "Protected (RECOMMENDED)\n    Blocks dangerous known commands.\n    Allows bypass for legitimate cases.",
        "zh": "受保护（推荐）\n    阻止已知的危险命令。\n    允许合法情况绕过。",
        "hi": "संरक्षित (अनुशंसित)\n    खतरनाक ज्ञात कमांड को ब्लॉक करता है।\n    वैध मामलों के लिए बाईपास की अनुमति देता है।",
        "es": "Protegido (RECOMENDADO)\n    Bloquea comandos peligrosos conocidos.\n    Permite bypass para casos legítimos.",
        "fr": "Protégé (RECOMMANDÉ)\n    Bloque les commandes dangereuses connues.\n    Permet le bypass pour les cas légitimes.",
        "ar": "محمي (موصى به)\n    يحظر الأوامر الخطيرة المعروفة.\n    يسمح بالتجاوز للحالات المشروعة.",
        "bn": "সুরক্ষিত (প্রস্তাবিত)\n    পরিচিত বিপজ্জনক কমান্ড ব্লক করে।\n    বৈধ ক্ষেত্রে বাইপাস অনুমতি দেয়।",
        "pt": "Protegido (RECOMENDADO)\n    Bloqueia comandos perigosos conhecidos.\n    Permite bypass para casos legítimos.",
        "ru": "Защищенный (РЕКОМЕНДУЕТСЯ)\n    Блокирует известные опасные команды.\n    Позволяет обход для легитимных случаев.",
        "ja": "保護（推奨）\n    既知の危険なコマンドをブロック。\n    正当なケースではバイパスを許可。",
    },
    "security_paranoid_desc": {
        "en": "Maximum security\n    Only whitelisted commands.\n    Very limited functionality.",
        "zh": "最高安全\n    仅白名单命令。\n    功能非常有限。",
        "hi": "अधिकतम सुरक्षा\n    केवल श्वेतसूची कमांड।\n    बहुत सीमित कार्यक्षमता।",
        "es": "Máxima seguridad\n    Solo comandos en lista blanca.\n    Funcionalidad muy limitada.",
        "fr": "Sécurité maximale\n    Uniquement les commandes en liste blanche.\n    Fonctionnalité très limitée.",
        "ar": "أقصى أمان\n    فقط الأوامر المدرجة في القائمة البيضاء.\n    وظائف محدودة جدا.",
        "bn": "সর্বোচ্চ নিরাপত্তা\n    শুধুমাত্র হোয়াইটলিস্ট করা কমান্ড।\n    খুব সীমিত কার্যকারিতা।",
        "pt": "Segurança máxima\n    Apenas comandos na lista branca.\n    Funcionalidade muito limitada.",
        "ru": "Максимальная безопасность\n    Только команды из белого списка.\n    Очень ограниченная функциональность.",
        "ja": "最大セキュリティ\n    ホワイトリストコマンドのみ。\n    非常に限定された機能。",
    },
    "security_choose_prompt": {
        "en": "Which mode do you want to use? [1/2/3] (default: 2)",
        "zh": "您想使用哪种模式？[1/2/3]（默认：2）",
        "hi": "आप कौन सा मोड उपयोग करना चाहते हैं? [1/2/3] (डिफ़ॉल्ट: 2)",
        "es": "¿Qué modo deseas usar? [1/2/3] (default: 2)",
        "fr": "Quel mode souhaitez-vous utiliser? [1/2/3] (défaut: 2)",
        "ar": "أي وضع تريد استخدامه؟ [1/2/3] (الافتراضي: 2)",
        "bn": "আপনি কোন মোড ব্যবহার করতে চান? [1/2/3] (ডিফল্ট: 2)",
        "pt": "Qual modo você quer usar? [1/2/3] (padrão: 2)",
        "ru": "Какой режим вы хотите использовать? [1/2/3] (по умолчанию: 2)",
        "ja": "どのモードを使用しますか？[1/2/3]（デフォルト：2）",
    },
    "security_free_warning": {
        "en": "⚠️ WARNING: FREE mode selected\nThis mode allows ARIA to execute ANY command.\nIncluding commands that can destroy your system.",
        "zh": "⚠️ 警告：已选择自由模式\n此模式允许ARIA执行任何命令。\n包括可能破坏系统的命令。",
        "hi": "⚠️ चेतावनी: FREE मोड चुना गया\nयह मोड ARIA को कोई भी कमांड चलाने की अनुमति देता है।\nजिसमें आपके सिस्टम को नष्ट करने वाले कमांड शामिल हैं।",
        "es": "⚠️ ADVERTENCIA: Modo FREE seleccionado\nEste modo permite que ARIA ejecute CUALQUIER comando.\nIncluyendo comandos que pueden destruir tu sistema.",
        "fr": "⚠️ AVERTISSEMENT: Mode LIBRE sélectionné\nCe mode permet à ARIA d'exécuter N'IMPORTE QUELLE commande.\nY compris des commandes qui peuvent détruire votre système.",
        "ar": "⚠️ تحذير: تم اختيار الوضع الحر\nهذا الوضع يسمح لـ ARIA بتنفيذ أي أمر.\nبما في ذلك الأوامر التي يمكن أن تدمر نظامك.",
        "bn": "⚠️ সতর্কতা: FREE মোড নির্বাচিত\nএই মোড ARIA কে যেকোনো কমান্ড চালানোর অনুমতি দেয়।\nযা আপনার সিস্টেম ধ্বংস করতে পারে।",
        "pt": "⚠️ AVISO: Modo LIVRE selecionado\nEste modo permite que ARIA execute QUALQUER comando.\nIncluindo comandos que podem destruir seu sistema.",
        "ru": "⚠️ ВНИМАНИЕ: выбран режим СВОБОДНЫЙ\nЭтот режим позволяет ARIA выполнять ЛЮБУЮ команду.\nВключая команды, которые могут уничтожить вашу систему.",
        "ja": "⚠️ 警告：フリーモードが選択されました\nこのモードではARIAがどんなコマンドでも実行できます。\nシステムを破壊するコマンドも含まれます。",
    },
    "security_mode_activated": {
        "en": "✓ {mode} mode activated for this session",
        "zh": "✓ {mode}模式已为此会话激活",
        "hi": "✓ इस सत्र के लिए {mode} मोड सक्रिय",
        "es": "✓ Modo {mode} activado para esta sesión",
        "fr": "✓ Mode {mode} activé pour cette session",
        "ar": "✓ تم تفعيل وضع {mode} لهذه الجلسة",
        "bn": "✓ এই সেশনের জন্য {mode} মোড সক্রিয়",
        "pt": "✓ Modo {mode} ativado para esta sessão",
        "ru": "✓ Режим {mode} активирован для этой сессии",
        "ja": "✓ このセッションで{mode}モードが有効",
    },
    "confirmed_by": {
        "en": "Confirmed by",
        "zh": "确认者",
        "hi": "द्वारा पुष्टि",
        "es": "Confirmado por",
        "fr": "Confirmé par",
        "ar": "تأكيد بواسطة",
        "bn": "দ্বারা নিশ্চিত",
        "pt": "Confirmado por",
        "ru": "Подтверждено",
        "ja": "確認者",
    },
    "session": {
        "en": "Session",
        "zh": "会话",
        "hi": "सत्र",
        "es": "Sesión",
        "fr": "Session",
        "ar": "جلسة",
        "bn": "সেশন",
        "pt": "Sessão",
        "ru": "Сессия",
        "ja": "セッション",
    },
    "invalid_confirmation": {
        "en": "Invalid confirmation. Using PROTECTED mode.",
        "zh": "确认无效。使用受保护模式。",
        "hi": "अमान्य पुष्टि। संरक्षित मोड का उपयोग।",
        "es": "Confirmación no válida. Usando modo PROTECTED.",
        "fr": "Confirmation invalide. Utilisation du mode PROTÉGÉ.",
        "ar": "تأكيد غير صالح. استخدام الوضع المحمي.",
        "bn": "অবৈধ নিশ্চিতকরণ। সুরক্ষিত মোড ব্যবহার করা হচ্ছে।",
        "pt": "Confirmação inválida. Usando modo PROTEGIDO.",
        "ru": "Неверное подтверждение. Используется режим ЗАЩИЩЕННЫЙ.",
        "ja": "無効な確認。保護モードを使用します。",
    },
    "invalid_option": {
        "en": "Invalid option. Please choose 1, 2 or 3.",
        "zh": "无效选项。请选择1、2或3。",
        "hi": "अमान्य विकल्प। कृपया 1, 2 या 3 चुनें।",
        "es": "Opción no válida. Por favor elige 1, 2 o 3.",
        "fr": "Option invalide. Veuillez choisir 1, 2 ou 3.",
        "ar": "خيار غير صالح. الرجاء اختيار 1 أو 2 أو 3.",
        "bn": "অবৈধ অপশন। অনুগ্রহ করে 1, 2 বা 3 বেছে নিন।",
        "pt": "Opção inválida. Por favor escolha 1, 2 ou 3.",
        "ru": "Неверный вариант. Пожалуйста, выберите 1, 2 или 3.",
        "ja": "無効なオプション。1、2、または3を選択してください。",
    },
    "interrupted_using_protected": {
        "en": "Interrupted. Using PROTECTED mode for safety.",
        "zh": "已中断。为安全起见使用受保护模式。",
        "hi": "बाधित। सुरक्षा के लिए संरक्षित मोड का उपयोग।",
        "es": "Interrumpido. Usando modo PROTECTED por seguridad.",
        "fr": "Interrompu. Utilisation du mode PROTÉGÉ par sécurité.",
        "ar": "توقف. استخدام الوضع المحمي للأمان.",
        "bn": "বাধাপ্রাপ্ত। নিরাপত্তার জন্য সুরক্ষিত মোড ব্যবহার।",
        "pt": "Interrompido. Usando modo PROTEGIDO por segurança.",
        "ru": "Прервано. Использование режима ЗАЩИЩЕННЫЙ для безопасности.",
        "ja": "中断されました。安全のため保護モードを使用します。",
    },
    "dangerous_action": {
        "en": "⚠️ Potentially dangerous action: {action}",
        "zh": "⚠️ 潜在危险操作：{action}",
        "hi": "⚠️ संभावित खतरनाक कार्रवाई: {action}",
        "es": "⚠️ Acción potencialmente peligrosa: {action}",
        "fr": "⚠️ Action potentiellement dangereuse: {action}",
        "ar": "⚠️ إجراء خطير محتمل: {action}",
        "bn": "⚠️ সম্ভাব্য বিপজ্জনক ক্রিয়া: {action}",
        "pt": "⚠️ Ação potencialmente perigosa: {action}",
        "ru": "⚠️ Потенциально опасное действие: {action}",
        "ja": "⚠️ 潜在的に危険な操作: {action}",
    },
    "continue_question": {
        "en": "Continue? [y/N]",
        "zh": "继续？[y/N]",
        "hi": "जारी रखें? [y/N]",
        "es": "¿Continuar? [s/N]",
        "fr": "Continuer? [o/N]",
        "ar": "متابعة؟ [y/N]",
        "bn": "চালিয়ে যান? [y/N]",
        "pt": "Continuar? [s/N]",
        "ru": "Продолжить? [д/Н]",
        "ja": "続行しますか？[y/N]",
    },
    "risk_level": {
        "en": "Risk level",
        "zh": "风险级别",
        "hi": "जोखिम स्तर",
        "es": "Nivel de riesgo",
        "fr": "Niveau de risque",
        "ar": "مستوى المخاطر",
        "bn": "ঝুঁকির স্তর",
        "pt": "Nível de risco",
        "ru": "Уровень риска",
        "ja": "リスクレベル",
    },
    "recommended_for": {
        "en": "Recommended for",
        "zh": "推荐用于",
        "hi": "के लिए अनुशंसित",
        "es": "Recomendado para",
        "fr": "Recommandé pour",
        "ar": "موصى به لـ",
        "bn": "জন্য প্রস্তাবিত",
        "pt": "Recomendado para",
        "ru": "Рекомендуется для",
        "ja": "推奨対象",
    },
    "warnings": {
        "en": "Warnings",
        "zh": "警告",
        "hi": "चेतावनियाँ",
        "es": "Advertencias",
        "fr": "Avertissements",
        "ar": "تحذيرات",
        "bn": "সতর্কতা",
        "pt": "Avisos",
        "ru": "Предупреждения",
        "ja": "警告",
    },
    "security_not_configured": {
        "en": "⚠️ Security not configured (using PROTECTED by default)",
        "zh": "⚠️ 安全未配置（默认使用受保护模式）",
        "hi": "⚠️ सुरक्षा कॉन्फ़िगर नहीं (डिफ़ॉल्ट रूप से संरक्षित)",
        "es": "⚠️ Seguridad no configurada (usando PROTECTED por defecto)",
        "fr": "⚠️ Sécurité non configurée (utilisant PROTÉGÉ par défaut)",
        "ar": "⚠️ الأمان غير مكوّن (استخدام محمي افتراضيًا)",
        "bn": "⚠️ নিরাপত্তা কনফিগার করা নেই (ডিফল্ট সুরক্ষিত)",
        "pt": "⚠️ Segurança não configurada (usando PROTEGIDO por padrão)",
        "ru": "⚠️ Безопасность не настроена (используется ЗАЩИЩЕННЫЙ по умолчанию)",
        "ja": "⚠️ セキュリティ未設定（デフォルトで保護モード使用）",
    },
}


# ============================================
# GLOBAL STATE
# ============================================

_current_language: Language = Language.ENGLISH
_language_saved: bool = False
_preferences_path: str = "data/user_preferences.yaml"


# ============================================
# CORE FUNCTIONS
# ============================================

def get_text(key: str, **kwargs) -> str:
    """Get translated text for current language"""
    lang_code = _current_language.value

    if key not in TRANSLATIONS:
        return f"[Missing translation: {key}]"

    text = TRANSLATIONS[key].get(lang_code, TRANSLATIONS[key].get("en", f"[{key}]"))

    # Replace placeholders
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass

    return text


def get_current_language() -> Language:
    """Get current language"""
    return _current_language


def get_language_name(lang: Language = None) -> str:
    """Get the native name of a language"""
    if lang is None:
        lang = _current_language
    return LANGUAGE_INFO[lang]["native_name"]


def set_language(lang: Language, save: bool = False) -> None:
    """Set the current language"""
    global _current_language, _language_saved

    _current_language = lang
    _language_saved = save

    if save:
        _save_language_preference(lang)


def _save_language_preference(lang: Language) -> None:
    """Save language preference to disk"""
    os.makedirs(os.path.dirname(_preferences_path), exist_ok=True)

    prefs = {}
    if os.path.exists(_preferences_path):
        try:
            import yaml
            with open(_preferences_path, 'r', encoding='utf-8') as f:
                prefs = yaml.safe_load(f) or {}
        except Exception:
            prefs = {}

    prefs['language'] = {
        'code': lang.value,
        'name': LANGUAGE_INFO[lang]['name'],
        'saved_at': datetime.now().isoformat()
    }

    try:
        import yaml
        with open(_preferences_path, 'w', encoding='utf-8') as f:
            yaml.dump(prefs, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        print(f"Warning: Could not save language preference: {e}")


def _load_language_preference() -> Optional[Language]:
    """Load saved language preference"""
    if not os.path.exists(_preferences_path):
        return None

    try:
        import yaml
        with open(_preferences_path, 'r', encoding='utf-8') as f:
            prefs = yaml.safe_load(f) or {}

        lang_code = prefs.get('language', {}).get('code')
        if lang_code:
            for lang in Language:
                if lang.value == lang_code:
                    return lang
    except Exception:
        pass

    return None


# ============================================
# LANGUAGE SELECTION UI
# ============================================

def display_language_menu() -> None:
    """Display the language selection menu"""
    print("\n" + "=" * 60)
    print("       SELECT YOUR LANGUAGE / SELECCIONA TU IDIOMA")
    print("              选择语言 / भाषा चुनें / 言語を選択")
    print("=" * 60 + "\n")

    languages = list(Language)
    for i, lang in enumerate(languages, 1):
        info = LANGUAGE_INFO[lang]
        print(f"  [{i:2}] {info['flag']}  {info['native_name']:20} ({info['name']})")

    print("\n" + "-" * 60)


def prompt_language_selection() -> Language:
    """Interactive prompt to select language"""

    # Check for saved preference first
    saved_lang = _load_language_preference()
    if saved_lang:
        info = LANGUAGE_INFO[saved_lang]
        print("\n" + "=" * 60)
        print(f"  {info['flag']} {get_text('previous_language_found', language=info['native_name'])}")
        print("=" * 60)
        print(f"\n  [1] {get_text('yes')} - {info['native_name']}")
        print(f"  [2] {get_text('change_language')}")
        print()

        try:
            choice = input("  [1/2]: ").strip()
            if choice == "" or choice == "1":
                set_language(saved_lang, save=True)
                return saved_lang
        except (KeyboardInterrupt, EOFError):
            set_language(saved_lang, save=True)
            return saved_lang

    # Show full language menu
    display_language_menu()

    languages = list(Language)

    while True:
        try:
            choice = input("\n  Enter number / Ingresa número [1-10]: ").strip()

            if choice == "":
                choice = "1"  # Default to English

            num = int(choice)
            if 1 <= num <= 10:
                selected_lang = languages[num - 1]
                break
            else:
                print("  Please enter a number between 1 and 10")

        except ValueError:
            print("  Please enter a valid number")
        except (KeyboardInterrupt, EOFError):
            print("\n  Using English as default")
            selected_lang = Language.ENGLISH
            break

    # Set language temporarily
    set_language(selected_lang, save=False)

    # Ask if they want to save
    info = LANGUAGE_INFO[selected_lang]
    print(f"\n  {info['flag']} {info['greeting']}!")
    print(f"\n  {get_text('save_preference_question')}")
    print(f"\n  [1] {get_text('yes_save')}")
    print(f"  [2] {get_text('no_this_session')}")

    try:
        save_choice = input("\n  [1/2]: ").strip()
        if save_choice == "" or save_choice == "1":
            set_language(selected_lang, save=True)
            print(f"\n  ✓ {get_text('language_saved', language=info['native_name'])}")
        else:
            print(f"\n  ✓ {get_text('language_session_only', language=info['native_name'])}")
    except (KeyboardInterrupt, EOFError):
        print(f"\n  {get_text('language_session_only', language=info['native_name'])}")

    print()
    return selected_lang


def change_language_command() -> Language:
    """Handle /language command to change language mid-session"""
    print(f"\n  {get_text('language_changed', language='...')}")
    display_language_menu()

    languages = list(Language)

    while True:
        try:
            choice = input(f"\n  {get_text('select_language_prompt')} [1-10]: ").strip()

            num = int(choice)
            if 1 <= num <= 10:
                selected_lang = languages[num - 1]
                break
            else:
                print("  1-10")

        except ValueError:
            print("  1-10")
        except (KeyboardInterrupt, EOFError):
            return _current_language

    # Ask if they want to save
    info = LANGUAGE_INFO[selected_lang]
    print(f"\n  {get_text('save_preference_question')}")
    print(f"\n  [1] {get_text('yes_save')}")
    print(f"  [2] {get_text('no_this_session')}")

    try:
        save_choice = input("\n  [1/2]: ").strip()
        save = (save_choice == "" or save_choice == "1")
    except (KeyboardInterrupt, EOFError):
        save = False

    set_language(selected_lang, save=save)

    if save:
        print(f"\n  ✓ {get_text('language_saved', language=info['native_name'])}")
    else:
        print(f"\n  ✓ {get_text('language_changed', language=info['native_name'])}")

    return selected_lang


# ============================================
# SYSTEM PROMPT FOR LLM
# ============================================

def get_language_system_prompt() -> str:
    """Get system prompt instructions for language handling"""
    lang = get_current_language()
    lang_name = LANGUAGE_INFO[lang]["native_name"]
    lang_english = LANGUAGE_INFO[lang]["name"]

    return f"""
=== LANGUAGE CONFIGURATION ===

The user has selected to communicate in: {lang_name} ({lang_english})

IMPORTANT INSTRUCTIONS:
1. ALWAYS respond in {lang_name} unless the user explicitly asks you to switch languages.
2. If the user says something like "speak to me in English" or "from now on use German" or similar requests to change language, acknowledge the change and switch to that language.
3. When switching languages, confirm the change in BOTH the old and new language.
4. Maintain natural, native-sounding {lang_name} - not machine-translated text.
5. Cultural context: Adapt your responses to be culturally appropriate for {lang_name} speakers.

Current language code: {lang.value}
"""


def detect_language_change_request(user_message: str) -> Optional[Language]:
    """
    Detect if user is asking to change language in natural language.
    Returns the requested language or None.
    """
    message_lower = user_message.lower()

    # Language change indicators in multiple languages
    change_phrases = [
        "speak", "talk", "respond", "answer", "write",  # English
        "habla", "responde", "escribe", "contesta",  # Spanish
        "parle", "réponds", "écris",  # French
        "说", "讲", "用",  # Chinese
        "話して", "答えて",  # Japanese
        "говори", "отвечай",  # Russian
        "fale", "responda",  # Portuguese
    ]

    # Check if message contains a language change request
    has_change_phrase = any(phrase in message_lower for phrase in change_phrases)

    if has_change_phrase:
        # Check for each language name
        for lang in Language:
            info = LANGUAGE_INFO[lang]
            lang_indicators = [
                info["name"].lower(),
                info["native_name"].lower(),
                lang.value,
            ]
            if any(indicator in message_lower for indicator in lang_indicators):
                return lang

    return None
