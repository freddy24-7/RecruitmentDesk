type Props = {
  /** What is happening. Read out by screen readers, and shown next to the spinner. */
  label: string
}

function Spinner({ label }: Props) {
  return (
    <p role="status" className="spinner">
      <span className="spinner-icon" aria-hidden="true" />
      {label}
    </p>
  )
}

export default Spinner
