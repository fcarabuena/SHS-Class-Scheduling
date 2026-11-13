export function AuthCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <p className="mb-2 text-center text-xs font-semibold uppercase tracking-widest text-primary-800">
          Senior High School · Class Scheduling
        </p>
        <div className="rounded-xl border border-stone-200 bg-white p-6 sm:p-8">
          <h1 className="text-xl font-semibold text-stone-900">{title}</h1>
          <p className="mb-6 mt-1 text-sm text-stone-600">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
