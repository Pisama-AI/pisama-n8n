import { Card, CardHeader, CardTitle, CardContent, Badge } from '@/components/ui'

// Foundation smoke page — proves the Pisama design system builds. Replaced by the
// real overview view next.
export default function Home() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-16">
      <h1 className="font-serif text-3xl text-ink mb-2">Pisama · n8n</h1>
      <p className="text-ink-3 mb-10">Self-hosted failure detection for n8n workflows.</p>
      <Card>
        <CardHeader>
          <CardTitle>Design system online</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-ink-2 mb-4">
            Broadsheet theme, amber evidence accent, reused from the Pisama frontend.
          </p>
          <Badge variant="success">ok</Badge>
        </CardContent>
      </Card>
    </main>
  )
}
