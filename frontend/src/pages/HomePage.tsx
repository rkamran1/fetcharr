import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function HomePage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Home</h1>
        </CardTitle>
        <CardDescription>Downloads will appear here in a later version.</CardDescription>
      </CardHeader>
    </Card>
  )
}
