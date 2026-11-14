export default function StatCard({
  title,
  value,
  unit,
  description,
  icon: Icon,
  footnote,
  accent = "orange",
}) {
  const accents = {
    orange: "bg-orange-500/10 text-orange-500",
    red: "bg-red-500/10 text-red-500",
    blue: "bg-blue-500/10 text-blue-500",
    green: "bg-emerald-500/10 text-emerald-500",
  };

  return (
    <div className="rounded-xl border border-(--border-color) bg-(--surface) p-5 transition hover:border-orange-500/40">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-(--text-secondary)">{title}</p>
        {Icon && (
          <div className={`rounded-lg p-2 ${accents[accent] ?? accents.orange}`}>
            <Icon size={19} />
          </div>
        )}
      </div>

      <div className="mt-4 flex items-baseline gap-1.5">
        <p className="text-2xl font-bold tracking-tight">{value}</p>
        {unit && <span className="text-xs text-(--text-secondary)">{unit}</span>}
      </div>

      {description && (
        <p className="mt-2 text-xs text-(--text-secondary)">{description}</p>
      )}

      {footnote && (
        <div className="mt-4 border-t border-(--border-color) pt-3">
          <span className="text-[11px] text-(--text-secondary)">{footnote}</span>
        </div>
      )}
    </div>
  );
}
