import * as React from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function StubPage({
  title,
  comingIn,
  description,
}: {
  title: string;
  comingIn: string;
  description: string;
}) {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10">
      <Card className="w-full max-w-2xl">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>coming in {comingIn}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{description}</p>
        </CardContent>
      </Card>
    </main>
  );
}
