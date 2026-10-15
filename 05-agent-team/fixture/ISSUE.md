# ISSUE-212: free plan goes over its rate limit

Reported by support, 2026-10-10.

The free plan allows 5 requests per second, with bursts up to 5. Right after a deploy the
limit holds. After the API has been up for a few minutes, a free-plan client sending
requests in a tight loop gets far more than 5 per second through, and the longer the
process has been up, the more requests get through.

Steps: start the API, wait two minutes, then send 50 requests as fast as possible with a
free-plan key. Expected: about 5 allowed. Actual: all 50 allowed.
