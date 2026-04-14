import AsyncStorage from '@react-native-async-storage/async-storage';
import en from './en.json';
import fr from './fr.json';
import frCA from './fr-CA.json';
import es from './es.json';

export type Language = 'en' | 'fr' | 'fr-CA' | 'es';

export const languages: { code: Language; name: string; nativeName: string }[] = [
    { code: 'en', name: 'English', nativeName: 'English' },
    { code: 'fr', name: 'French', nativeName: 'Français' },
    { code: 'fr-CA', name: 'French (Canada)', nativeName: 'Français (Canada)' },
    { code: 'es', name: 'Spanish', nativeName: 'Español' },
];

const LANGUAGE_KEY = '@spinr_language';

type TranslationValue = string | { [key: string]: TranslationValue };
type Translations = { [key: string]: TranslationValue };

const translations: Record<Language, Translations> = {
    en: en as Translations,
    fr: fr as Translations,
    'fr-CA': frCA as Translations,
    es: es as Translations,
};

// Fallback chain: if a key is missing in the requested language, fall back through this list.
// fr-CA falls back to fr, then to en. Others fall back directly to en.
const fallbackChain: Record<Language, Language[]> = {
    en: [],
    fr: ['en'],
    'fr-CA': ['fr', 'en'],
    es: ['en'],
};

export async function getStoredLanguage(): Promise<Language> {
    try {
        const stored = await AsyncStorage.getItem(LANGUAGE_KEY);
        if (stored === 'en' || stored === 'fr' || stored === 'fr-CA' || stored === 'es') {
            return stored;
        }
        return 'en';
    } catch {
        return 'en';
    }
}

export async function setStoredLanguage(language: Language): Promise<void> {
    try {
        await AsyncStorage.setItem(LANGUAGE_KEY, language);
    } catch (error) {
        console.error('Failed to store language:', error);
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

export function translate(language: Language, key: string): string {
    const direct = getNestedValue(translations[language], key);
    if (direct !== null) return direct;

    // Walk the fallback chain to find a defined value
    for (const fallback of fallbackChain[language]) {
        const value = getNestedValue(translations[fallback], key);
        if (value !== null) return value;
    }

    // Last resort: return the key itself (preserves old behaviour)
    return key;
}

export { translations };
