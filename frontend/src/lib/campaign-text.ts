// Campaign content (questions, choices, sections, outcomes, names) in the interface language. Campaigns are data
// written by admins in one language, so each text is shown, in order: the translation the admin typed (`tr`), the
// built-in translation of the campaigns the app creates (locales/*/campaign-defaults.ts), or the text as written.
import { useMemo } from "react";
import { useApi } from "@/lib/api";
import { getLocale, useT } from "@/lib/i18n";
import type { OpCampaign, OpConfig, OpOutcome, OpQuestion } from "@/lib/types";
import { campaignDefaults as ar } from "@/locales/ar/campaign-defaults";
import { campaignDefaults as fr } from "@/locales/fr/campaign-defaults";

/** Languages a campaign text can be translated to (English is what admins write in). */
export const CAMPAIGN_LANGS = ["fr", "ar"] as const;
export type CampaignLang = (typeof CAMPAIGN_LANGS)[number];

const BUILT_IN: Record<CampaignLang, Record<string, string>> = { ar, fr };

const lang = (): CampaignLang | null => {
  const locale = getLocale();
  return locale === "en" ? null : locale;
};

/** The built-in translation of a text, if the app ships one (shown as a hint in the campaign editor). */
export function builtInText(text: string | null | undefined, to: CampaignLang): string | undefined {
  return text ? BUILT_IN[to][text] : undefined;
}

/** A campaign text in the current language: `typed` (the admin's translation) first, then the built-in one. */
export function campaignText(text: string, typed?: string): string;
export function campaignText(text: string | undefined, typed?: string): string | undefined;
export function campaignText(text: string | null, typed?: string): string | null;
export function campaignText(text: string | null | undefined, typed?: string): string | null | undefined;
export function campaignText(text: string | null | undefined, typed?: string) {
  const to = lang();
  if (!to || !text) return text;
  return typed || BUILT_IN[to][text] || text;
}

function localizeQuestion(q: OpQuestion, sections: Map<string, string>): OpQuestion {
  const to = lang();
  const tr = to ? q.tr?.[to] : undefined;
  return {
    ...q,
    help: campaignText(q.help, tr?.help),
    label: campaignText(q.label, tr?.label),
    options: q.options?.map(([value, label]) => [value, campaignText(label, tr?.options?.[value])]),
    section: sections.get(q.section) ?? campaignText(q.section),
    unit: campaignText(q.unit, tr?.unit),
  };
}

export function localizeOutcome(o: OpOutcome): OpOutcome {
  const to = lang();
  return { ...o, label: campaignText(o.label, to ? o.tr?.[to]?.label : undefined) };
}

export function localizeCampaign(c: OpCampaign): OpCampaign {
  const to = lang();
  if (!to) return c;
  // Questions are grouped by section: a section translated on one of its questions names the whole group.
  const sections = new Map<string, string>();
  for (const q of c.questions) {
    const typed = q.tr?.[to]?.section;
    if (typed && !sections.has(q.section)) sections.set(q.section, typed);
  }
  return {
    ...c,
    description: campaignText(c.description),
    name: campaignText(c.name),
    outcomes: c.outcomes.map(localizeOutcome),
    questions: c.questions.map((q) => localizeQuestion(q, sections)),
  };
}

export function localizeConfig(config: OpConfig): OpConfig {
  if (!lang()) return config;
  return { ...config, campaigns: config.campaigns.map(localizeCampaign), outcomes: config.outcomes.map(localizeOutcome) };
}

/** The call desk config with its campaigns in the interface language. Not for editing: see useApi for the raw one. */
export function useOpConfig() {
  const { locale } = useT();
  const result = useApi<OpConfig>("/api/operations/config");
  // localizeConfig reads the current language: `locale` re-runs it when that changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const data = useMemo(() => (result.data ? localizeConfig(result.data) : undefined), [result.data, locale]);
  return { ...result, data };
}
