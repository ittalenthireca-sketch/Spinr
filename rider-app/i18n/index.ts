/**
 * Rider-app i18n bootstrap.
 *
 * Mirrors the driver-app i18n pattern (see driver-app/i18n/index.ts).
 * Provides a lightweight translate() helper backed by JSON dictionaries with
 * a fallback chain (fr-CA -> en). Default language is derived from the device
 * locale via expo-localization, falling back to 'en' if the locale is not
 * supported.
 *
 * Screen-level adoption of t() is out of scope for this scaffold; individual
 * screens can migrate to t() incrementally in follow-up tickets.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import en from './en.json';
import frCA from './fr-CA.json';

export type Language = 'en' | 'fr-CA';

export const languages: { code: Language; name: string; nativeName: string }[] = [
    { code: 'en', name: 'English', nativeName: 'English' },
    { code: 'fr-CA', name: 'French (Canada)', nativeName: 'Français (Canada)' },
];

const LANGUAGE_KEY = '@spinr_rider_language';

type TranslationValue = string | { [key: string]: TranslationValue };
type Translations = { [key: string]: TranslationValue };

const translations: Record<Language, Translations> = {
    en: en as Translations,
    'fr-CA': frCA as Translations,
};

const fallbackChain: Record<Language, Language[]> = {
    en: [],
    'fr-CA': ['en'],
};

/**
 * Infer the best supported Language from a raw locale tag (e.g. "fr-CA",
 * "fr_CA", "fr", "en-US"). Returns 'en' if nothing matches.
 */
export function resolveDeviceLanguage(rawLocale: string | null | undefined): Language {
    if (!rawLocale) return 'en';
    const normalized = rawLocale.replace('_', '-');
    if (normalized === 'fr-CA' || normalized.toLowerCase().startsWith('fr-ca')) {
        return 'fr-CA';
    }
    if (normalized.toLowerCase().startsWith('fr')) {
        // No metro-French dictionary in rider-app yet; fall back to fr-CA
        // since it is the closest supported French variant.
        return 'fr-CA';
    }
    return 'en';
}

/**
 * Read the stored language preference. Falls back to the device locale
 * (via expo-localization when available) and finally to 'en'.
 */
export async function getStoredLanguage(): Promise<Language> {
    try {
        const stored = await AsyncStorage.getItem(LANGUAGE_KEY);
        if (stored === 'en' || stored === 'fr-CA') {
            return stored;
        }
    } catch {
        // ignore and fall through to device locale
    }

    try {
        // Lazy-require so tests / non-Expo contexts don't need expo-localization.
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const Localization = require('expo-localization') as {
            getLocales?: () => { languageTag?: string; languageCode?: string }[];
            locale?: string;
        };
        const locales = Localization.getLocales?.();
        const tag = locales && locales.length > 0
            ? (locales[0].languageTag ?? locales[0].languageCode)
            : Localization.locale;
        return resolveDeviceLanguage(tag);
    } catch {
        return 'en';
    }
}

export async function setStoredLanguage(language: Language): Promise<void> {
    try {
        await AsyncStorage.setItem(LANGUAGE_KEY, language);
    } catch (error) {
        console.error('Failed to store rider-app language:', error);
    }
}

export function getNestedValue(obj: Translations, path: string): string | null {
    const keys = path.split('.');
    let current: TranslationValue = obj;

    for (const key of keys) {
        if (current && typeof current === 'object' && key in current) {
            current = (current as { [key: string]: TranslationValue })[key];
        } else {
            return null;
        }
    }

    return typeof current === 'string' ? current : null;
}

/**
 * Translate a dotted key for the given language, walking the fallback chain
 * if the key is missing. Returns the key itself as a last resort so missing
 * strings are obvious in the UI.
 */
export function translate(language: Language, key: string): string {
    const direct = getNestedValue(translations[language], key);
    if (direct !== null) return direct;

    for (const fallback of fallbackChain[language]) {
        const value = getNestedValue(translations[fallback], key);
        if (value !== null) return value;
    }

    return key;
}

export { translations };
