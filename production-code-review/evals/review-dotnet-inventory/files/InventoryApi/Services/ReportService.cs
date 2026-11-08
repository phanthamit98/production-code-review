using System.Net.Http.Json;

namespace InventoryApi.Services;

public interface IReportService
{
    Task<decimal> GetExchangeRateAsync(string currency, CancellationToken ct);
}

public record RateResponse(decimal Rate);

public class ReportService(IConfiguration configuration) : IReportService
{
    public async Task<decimal> GetExchangeRateAsync(string currency, CancellationToken ct)
    {
        using var client = new HttpClient();
        var baseUrl = configuration["Rates:BaseUrl"]
            ?? throw new InvalidOperationException("Rates:BaseUrl is not configured.");

        var response = await client.GetFromJsonAsync<RateResponse>(
            $"{baseUrl}/rates/{Uri.EscapeDataString(currency)}", ct);

        return response?.Rate ?? throw new InvalidOperationException($"No rate returned for {currency}.");
    }
}
