using System.ComponentModel.DataAnnotations;

namespace InventoryApi.Dtos;

public record ProductResponse(int Id, string Name, string Category, decimal Price, int Stock);

public class RestockRequest
{
    [Range(1, 10_000)]
    public int Quantity { get; set; }
}
