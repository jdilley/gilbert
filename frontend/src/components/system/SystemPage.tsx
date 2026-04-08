import { useQuery } from "@tanstack/react-query";
import { fetchServices } from "@/api/system";
import { ServiceCard } from "./ServiceCard";

export function SystemPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["system-services"],
    queryFn: fetchServices,
  });

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold">System Browser</h1>
      <div className="space-y-3">
        {data?.services.map((svc) => (
          <ServiceCard key={svc.name} service={svc} />
        ))}
      </div>
    </div>
  );
}
