import { LanguagesIcon } from "lucide-react";
import type * as React from "react";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { type Locale, LOCALES, useT } from "@/lib/i18n";

const ITEMS = LOCALES.map((l) => ({ label: l.label, value: l.value }));

/** The interface language, saved in this browser. */
export function LanguageSelect({ className }: { className?: string }): React.ReactElement {
  const { t, locale, setLocale } = useT();
  return (
    <Select items={ITEMS} onValueChange={(v) => setLocale(v as Locale)} value={locale}>
      <SelectTrigger aria-label={t("shell.language")} className={className} size="sm">
        <LanguagesIcon aria-hidden="true" className="size-4 opacity-72" />
        <SelectValue />
      </SelectTrigger>
      <SelectPopup>
        {LOCALES.map((l) => (
          <SelectItem key={l.value} value={l.value}>
            <span dir={l.dir} lang={l.value}>
              {l.label}
            </span>
          </SelectItem>
        ))}
      </SelectPopup>
    </Select>
  );
}
