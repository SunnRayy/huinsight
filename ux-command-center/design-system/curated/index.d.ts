// Huinsight components — types copied from ux-command-center/components/operations/*.tsx and components/BrandMark.tsx.
// Global: window.Huinsight (reads window.React / window.ReactDOM).
import * as React from 'react';

/** The Huinsight mark — 慧眼, an almond eye whose iris is cut into six facets. 48px and up. */
export interface BrandMarkProps { className?: string; title?: string }
export declare const BrandMark: React.FC<BrandMarkProps>;

/** Material Symbols Outlined glyph by ligature name ("sync", "trending_up"). */
export interface IconProps { name: string; size?: number; fill?: boolean; color?: string; style?: React.CSSProperties }
export declare function Icon(props: IconProps): React.ReactElement;

export interface CardProps { children: React.ReactNode; padding?: number | string; style?: React.CSSProperties }
export declare function Card(props: CardProps): React.ReactElement;

export type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';
export interface PillProps { children?: React.ReactNode; tone?: Tone; style?: React.CSSProperties }
export declare function Pill(props: PillProps): React.ReactElement;
/** status: ok | healthy | warning | review | high | low | info | missing (unknown → neutral, shown verbatim). */
export interface StatusPillProps { status: string; children?: React.ReactNode }
export declare function StatusPill(props: StatusPillProps): React.ReactElement;

export interface ChipBtnProps { children?: React.ReactNode; icon?: string; onClick?: () => void; primary?: boolean; style?: React.CSSProperties; disabled?: boolean }
export declare function ChipBtn(props: ChipBtnProps): React.ReactElement;
export interface ActionBtnProps { children?: React.ReactNode; icon?: string; variant?: 'primary' | 'secondary'; onClick?: () => void; disabled?: boolean; danger?: boolean }
export declare function ActionBtn(props: ActionBtnProps): React.ReactElement;
export interface IconBtnProps { icon: string; title?: string; danger?: boolean; onClick?: () => void; ariaLabel?: string; ariaExpanded?: boolean; ariaDescribedBy?: string }
export declare function IconBtn(props: IconBtnProps): React.ReactElement;

export interface OpsKpiProps { label: string; value: string | number; sub?: string; subColor?: string; accent?: string; icon?: string; dense?: boolean }
export declare function OpsKpi(props: OpsKpiProps): React.ReactElement;

export interface SectionProps { title?: string; eyebrow?: string; icon?: string; right?: React.ReactNode; children: React.ReactNode; style?: React.CSSProperties }
export declare function Section(props: SectionProps): React.ReactElement;
export interface SectionTitleProps { icon?: string; title: string; right?: React.ReactNode; style?: React.CSSProperties }
export declare function SectionTitle(props: SectionTitleProps): React.ReactElement;

/** status: ok (default) | warning | error. */
export interface SourceChipProps { name: string; status?: string; count?: number }
export declare function SourceChip(props: SourceChipProps): React.ReactElement;
/** sev: high | review | info | anything else (= ok, green). */
export interface SevDotProps { sev: string }
export declare function SevDot(props: SevDotProps): React.ReactElement;

export interface ColDef<T = Record<string, unknown>> {
  label: string; key?: string; render?: (row: T) => React.ReactNode;
  align?: 'left' | 'right' | 'center'; padX?: number; mono?: boolean; size?: number;
  color?: string; nowrap?: boolean; width?: number | string;
}
export interface OpsTableProps<T = Record<string, unknown>> {
  cols: ColDef<T>[]; rows: T[]; onRowClick?: (row: T) => void;
  density?: 'compact' | 'dense' | 'comfy'; rowKey?: (row: T) => string | number; selectedKey?: string | number | null;
}
export declare function OpsTable<T = Record<string, unknown>>(props: OpsTableProps<T>): React.ReactElement;

export interface MiniLineProps { data: { m?: string; [key: string]: unknown }[]; width?: number; height?: number; accessor?: string; targetAccessor?: string | null }
export declare function MiniLine(props: MiniLineProps): React.ReactElement | null;

export interface DriftGaugeProps { drift: number; tolerance?: number }
export declare function DriftGauge(props: DriftGaugeProps): React.ReactElement;
export interface DriftRowProps { current: number; target: number; color?: string }
export declare function DriftRow(props: DriftRowProps): React.ReactElement;

export interface ToolbarProps { children: React.ReactNode; style?: React.CSSProperties }
export declare function Toolbar(props: ToolbarProps): React.ReactElement;
export interface SearchInputProps { value: string; onChange: (v: string) => void; placeholder?: string; width?: number | string }
export declare function SearchInput(props: SearchInputProps): React.ReactElement;
export interface OpsSelectProps { value: string; onChange: (v: string) => void; options: (string | { value: string; label: string })[]; label?: string; width?: number | string }
export declare function OpsSelect(props: OpsSelectProps): React.ReactElement;

export interface ModalShellProps { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; closeLabel?: string }
export declare function ModalShell(props: ModalShellProps): React.ReactElement;
export declare function FieldLabel(props: { children: React.ReactNode; htmlFor?: string }): React.ReactElement;
export interface FormInputProps { value: string; onChange: (value: string) => void; placeholder?: string; type?: string; mono?: boolean; id?: string; maxLength?: number }
export declare function FormInput(props: FormInputProps): React.ReactElement;
export interface FormSelectProps { value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }
export declare function FormSelect(props: FormSelectProps): React.ReactElement;
export interface FormTextareaProps { value: string; onChange: (value: string) => void; placeholder?: string; rows?: number; id?: string; maxLength?: number }
export declare function FormTextarea(props: FormTextareaProps): React.ReactElement;

export interface CardHeaderProps { icon?: string; title: string; sub?: React.ReactNode; right?: React.ReactNode }
export declare function CardHeader(props: CardHeaderProps): React.ReactElement;
export interface InfoTipProps { label: string; children: React.ReactNode }
export declare function InfoTip(props: InfoTipProps): React.ReactElement;
export interface NoticeProps { tone?: 'success' | 'danger' | 'warning' | 'info'; children: React.ReactNode; detail?: React.ReactNode; action?: React.ReactNode }
export declare function Notice(props: NoticeProps): React.ReactElement;
