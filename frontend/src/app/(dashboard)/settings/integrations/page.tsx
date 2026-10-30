"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function SettingsIntegrationsRedirectContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const qs = searchParams.toString();
    router.replace(`/integrations${qs ? `?${qs}` : ""}`);
  }, [router, searchParams]);

  return (
    <div className="flex items-center justify-center p-12 text-xs text-muted-foreground">
      Redirecting to integrations...
    </div>
  );
}

export default function SettingsIntegrationsRedirect() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center p-12 text-xs text-muted-foreground">
          Redirecting to integrations...
        </div>
      }
    >
      <SettingsIntegrationsRedirectContent />
    </Suspense>
  );
}
