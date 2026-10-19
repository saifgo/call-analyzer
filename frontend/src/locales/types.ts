type PluralForm = "zero" | "one" | "two" | "few" | "many" | "other";
type PluralBase<T> = keyof T extends infer K ? (K extends `${infer B}_other` ? B : never) : never;

/** A translation of the English namespace T: every key, plus optional extra plural forms (Arabic has six). */
export type Translation<T> = Record<keyof T, string> & Partial<Record<`${PluralBase<T>}_${PluralForm}`, string>>;
