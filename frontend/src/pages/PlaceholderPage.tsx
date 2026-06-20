import { Construction } from "lucide-react";

import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui";

export function PlaceholderPage({ title, description }: { title: string; description?: string }) {
  return (
    <div>
      <PageHeader title={title} description={description} />
      <Card className="flex flex-col items-center justify-center gap-3 p-12 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
          <Construction className="h-6 w-6" />
        </span>
        <div className="text-sm font-medium text-slate-700">
          This screen is being built next
        </div>
        <p className="max-w-sm text-sm text-slate-400">
          The backend API for this area is ready. The interface is being added screen by screen.
        </p>
      </Card>
    </div>
  );
}
