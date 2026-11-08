using System.Security.Claims;
using InventoryApi.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace InventoryApi.Controllers;

[ApiController]
[Route("api/orders")]
[Authorize]
public class OrdersController(IOrderService orders) : ControllerBase
{
    [HttpGet("{id:int}")]
    public async Task<IActionResult> Get(int id)
    {
        var order = await orders.GetByIdAsync(id);
        return order is null ? NotFound() : Ok(order);
    }

    [HttpGet("mine")]
    public IActionResult Mine()
    {
        var userId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
        var result = orders.GetForUserAsync(userId).Result;
        return Ok(result);
    }

    [HttpPost("{id:int}/cancel")]
    public async Task<IActionResult> Cancel(int id)
    {
        var userId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
        var cancelled = await orders.CancelAsync(id, userId);
        return cancelled ? NoContent() : NotFound();
    }
}
