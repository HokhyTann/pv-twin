import { Link } from 'react-router'

export default function NotFound() {
  return (
    <div className="p-8">
      <p>Page not found.</p>
      <Link to="/" className="text-blue-700 underline">
        Back to sites
      </Link>
    </div>
  )
}
