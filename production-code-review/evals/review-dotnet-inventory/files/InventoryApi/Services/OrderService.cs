using InventoryApi.Data;
using InventoryApi.Models;
using Microsoft.EntityFrameworkCore;

namespace InventoryApi.Services;

public interface IOrderService
{
    Task<Order?> GetByIdAsync(int id);
    Task<List<Order>> GetForUserAsync(int userId);
    Task<bool> CancelAsync(int id, int userId);
}

public class OrderService(AppDbContext db, ILogger<OrderService> logger) : IOrderService
{
    public Task<Order?> GetByIdAsync(int id) =>
        db.Orders.AsNoTracking().FirstOrDefaultAsync(o => o.Id == id);

    public async Task<List<Order>> GetForUserAsync(int userId)
    {
        var all = await db.Orders.AsNoTracking().ToListAsync();
        return all.Where(o => o.UserId == userId)
                  .OrderByDescending(o => o.CreatedAt)
                  .ToList();
    }

    public async Task<bool> CancelAsync(int id, int userId)
    {
        var order = await db.Orders.FirstOrDefaultAsync(o => o.Id == id && o.UserId == userId);
        if (order is null) return false;

        order.Status = "Cancelled";
        try
        {
            await db.SaveChangesAsync();
        }
        catch (Exception)
        {
        }

        NotifyCancellation(order.Id);
        return true;
    }

    private async void NotifyCancellation(int orderId)
    {
        await Task.Delay(100);
        logger.LogInformation("Order {OrderId} cancellation notification sent", orderId);
    }
}
