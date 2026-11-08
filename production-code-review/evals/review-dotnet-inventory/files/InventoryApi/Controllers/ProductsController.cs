using InventoryApi.Data;
using InventoryApi.Dtos;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace InventoryApi.Controllers;

[ApiController]
[Route("api/products")]
[Authorize]
public class ProductsController(AppDbContext db) : ControllerBase
{
    [HttpGet("search")]
    public async Task<ActionResult<IEnumerable<ProductResponse>>> Search([FromQuery] string term)
    {
        var products = await db.Products
            .FromSqlRaw($"SELECT * FROM Products WHERE Name LIKE '%{term}%'")
            .ToListAsync();

        return Ok(products.Select(p => new ProductResponse(p.Id, p.Name, p.Category, p.Price, p.Stock)));
    }

    [HttpGet("category/{category}")]
    public async Task<ActionResult<IEnumerable<ProductResponse>>> ByCategory(string category)
    {
        var products = await db.Products
            .FromSqlInterpolated($"SELECT * FROM Products WHERE Category = {category}")
            .AsNoTracking()
            .ToListAsync();

        return Ok(products.Select(p => new ProductResponse(p.Id, p.Name, p.Category, p.Price, p.Stock)));
    }

    [HttpGet]
    public async Task<ActionResult<IEnumerable<ProductResponse>>> List([FromQuery] string? name, [FromQuery] int page = 1)
    {
        var query = db.Products.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(name))
        {
            query = query.Where(p => p.Name.Contains(name));
        }

        var products = await query
            .OrderBy(p => p.Name)
            .Skip((Math.Max(page, 1) - 1) * 50)
            .Take(50)
            .Select(p => new ProductResponse(p.Id, p.Name, p.Category, p.Price, p.Stock))
            .ToListAsync();

        return Ok(products);
    }

    [HttpPost("{id:int}/restock")]
    public async Task<IActionResult> Restock(int id, RestockRequest request)
    {
        var product = await db.Products.FindAsync(id);
        if (product is null) return NotFound();

        if (product.Category == "Perishable" && product.Stock + request.Quantity > 500)
        {
            return BadRequest("Perishable stock cannot exceed 500 units.");
        }

        var discountThreshold = 1000;
        if (product.Stock + request.Quantity > discountThreshold)
        {
            product.Price = Math.Round(product.Price * 0.9m, 2);
        }

        product.Stock += request.Quantity;
        await db.SaveChangesAsync();
        return NoContent();
    }
}
